"""
graph.py

Assembles the Collaborative Investment Research Platform's LangGraph
StateGraph: node wiring, parallel fan-out, conditional routing, and the
3 HITL interrupt points (Checkpoint #1 company confirmation, Checkpoint #2
investment committee approval, total-data-failure). A "revise" decision at
Checkpoint #2 cycles back to build_memo with committee feedback, so the
Orchestrator updates its thesis/recommendation rather than starting over.

NOTE on topology -- synchronization barrier: Industry Identification is
deterministic (no LLM call) and runs in parallel with Sentiment Analyst
right after Checkpoint #1, then feeds Financial Analyst and Macro &
Industry Analyst. That shape is an asymmetric-depth diamond: Sentiment's
path reaches `data_failure_check` in 1 hop from the fan-out, while
Financial/Macro's path takes 2 hops (via industry_identification). Testing
found that this specific asymmetry -- not the diamond shape itself --
reproducibly corrupts execution in LangGraph 1.2.10 once combined with the
multi-interrupt Checkpoint #2 loop downstream (verified via isolated
minimal repros: symmetric-depth fan-in works cleanly; asymmetric-depth
fan-in causes an `InvalidUpdateError`, or with a permissive channel
reducer, a spurious duplicate interrupt). The fix is `sentiment_sync`: a
trivial no-op node that gives Sentiment's path the same 2-hop depth as
Financial/Macro's, so all 3 branches arrive at `data_failure_check` in the
same superstep. It does no work -- it exists purely to satisfy this
LangGraph version's synchronization assumption.
"""

import sqlite3
from typing import Union

import yfinance as yf
from langgraph.checkpoint.sqlite import SqliteSaver
from langgraph.graph import END, START, StateGraph
from langgraph.types import interrupt

from agents import financial_analyst, intake_validation, macro_industry_analyst, orchestrator, sentiment_analyst
from config import CHECKPOINT_DB
from state import InvestmentResearchState
from tools.a2a_router import register_handler


def industry_identification_node(state: dict) -> dict:
    """
    Deterministic, NOT an agent -- no LLM call. Runs in PARALLEL with the
    Sentiment Analyst, immediately after Checkpoint #1 confirms, then feeds
    Financial Analyst and Macro & Industry Analyst.
    """
    ticker = state.get("ticker")
    try:
        info = yf.Ticker(ticker).info or {}
        sector = info.get("sector")
        industry = info.get("industry")
    except Exception:
        sector, industry = None, None
    return {"sector": sector, "industry": industry}


def sentiment_sync_node(state: dict) -> dict:
    """No-op synchronization barrier -- see module docstring."""
    return {}


def data_failure_check_node(state: dict) -> dict:
    """
    Runs after the 3 specialists finish in parallel, before the Orchestrator.
    1 or 2 failures -> pass through silently (the Orchestrator discloses
    `data_gaps` in the memo). ALL 3 failed -> hard stop, interrupt(), offer
    retry. This is the ONLY data-related interrupt.
    """
    all_failed = bool(state.get("sentiment_failed") and state.get("financial_failed") and state.get("macro_failed"))
    if not all_failed:
        return {}

    interrupt({
        "type": "total_data_failure",
        "message": (
            "We couldn't complete research on this company -- sentiment, financial, and "
            "macro/industry data were all unavailable right now. Respond to retry."
        ),
    })
    return {}


def route_after_intake(state: dict) -> Union[str, list]:
    if state.get("intake_status") == "confirmed":
        # Industry Identification and Sentiment Analyst both start
        # immediately after Checkpoint #1, in parallel -- not sequentially.
        return ["industry_identification", "sentiment_analyst"]
    # private_company / not_found / pending (user said No) -- this turn ends;
    # the next user message starts a fresh graph invocation at intake_validation.
    return END


def route_after_data_check(state: dict) -> Union[str, list]:
    all_failed = bool(state.get("sentiment_failed") and state.get("financial_failed") and state.get("macro_failed"))
    if all_failed:
        # Restart the same fan-out point used initially (rather than the
        # specialists directly) so the retry preserves the exact depth-
        # matched topology verified safe -- see module docstring.
        return ["industry_identification", "sentiment_analyst"]
    return "build_memo"


def route_after_checkpoint_2(state: dict) -> str:
    # "revise" sends feedback back to build_memo to update the thesis/
    # recommendation (a 2-node cycle, not a diamond fan-in -- safe per the
    # LangGraph limitation documented above). approved/rejected end the run.
    if state.get("committee_decision") == "revise":
        return "build_memo"
    return END


def build_graph() -> StateGraph:
    register_handler("sentiment_analyst", sentiment_analyst.answer_question)
    register_handler("financial_analyst", financial_analyst.answer_question)
    register_handler("macro_industry_analyst", macro_industry_analyst.answer_question)

    graph = StateGraph(InvestmentResearchState)

    graph.add_node("intake_validation", intake_validation.intake_validation_node)
    graph.add_node("industry_identification", industry_identification_node)
    graph.add_node("sentiment_analyst", sentiment_analyst.sentiment_analyst_node)
    graph.add_node("sentiment_sync", sentiment_sync_node)
    graph.add_node("financial_analyst", financial_analyst.financial_analyst_node)
    graph.add_node("macro_industry_analyst", macro_industry_analyst.macro_industry_analyst_node)
    graph.add_node("data_failure_check", data_failure_check_node)
    graph.add_node("build_memo", orchestrator.build_memo_node)
    graph.add_node("checkpoint_2_review", orchestrator.checkpoint_2_review_node)

    graph.add_edge(START, "intake_validation")
    graph.add_conditional_edges("intake_validation", route_after_intake)

    # Industry Identification feeds the two specialists that need industry/sector.
    graph.add_edge("industry_identification", "financial_analyst")
    graph.add_edge("industry_identification", "macro_industry_analyst")

    # Sentiment routes through the sync barrier so its path reaches
    # data_failure_check at the same depth as Financial/Macro's.
    graph.add_edge("sentiment_analyst", "sentiment_sync")
    graph.add_edge("sentiment_sync", "data_failure_check")
    graph.add_edge("financial_analyst", "data_failure_check")
    graph.add_edge("macro_industry_analyst", "data_failure_check")

    graph.add_conditional_edges("data_failure_check", route_after_data_check)

    graph.add_edge("build_memo", "checkpoint_2_review")
    graph.add_conditional_edges("checkpoint_2_review", route_after_checkpoint_2)

    return graph


def compile_graph(db_path: str = None):
    """Compile the graph with a SQLite checkpointer (required for interrupt()/Command(resume=...))."""
    conn = sqlite3.connect(db_path or CHECKPOINT_DB, check_same_thread=False)
    checkpointer = SqliteSaver(conn)
    return build_graph().compile(checkpointer=checkpointer)
