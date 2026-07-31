"""
graph.py

Assembles the Collaborative Investment Research Platform's LangGraph
StateGraph: node wiring, parallel fan-out, conditional routing, and the
3 HITL interrupt points (Checkpoint #1, Checkpoint #2, total-data-failure).

NOTE on topology: Industry Identification is deterministic (no LLM call,
per the brief) and conceptually runs "in parallel with Sentiment Analyst,
right after Checkpoint #1." It is NOT wired as its own graph node feeding
into Financial Analyst / Macro & Industry Analyst -- that shape (an
asymmetric-depth diamond converging before a multi-interrupt Q&A node)
triggered a reproducible LangGraph 1.2.10 bug (corrupted/duplicated
execution on resume, see agents/financial_analyst.py and
agents/macro_industry_analyst.py docstrings). Instead, Financial Analyst
and Macro & Industry Analyst each resolve industry/sector inline (a cheap,
already-fetched yfinance lookup) at the start of their own execution, and
all 3 specialists fan out flatly and simultaneously from Checkpoint #1.
"""

import sqlite3
from typing import Union

from langgraph.checkpoint.sqlite import SqliteSaver
from langgraph.graph import END, START, StateGraph
from langgraph.types import interrupt

from agents import financial_analyst, intake_validation, macro_industry_analyst, orchestrator, sentiment_analyst
from config import CHECKPOINT_DB
from state import InvestmentResearchState
from tools.a2a_router import register_handler


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
        # All 3 specialists start immediately after Checkpoint #1, in
        # parallel -- Sentiment Analyst doesn't need industry/sector, and
        # Financial/Macro each resolve it themselves (see module docstring).
        return ["sentiment_analyst", "financial_analyst", "macro_industry_analyst"]
    # private_company / not_found / pending (user said No) -- this turn ends;
    # the next user message starts a fresh graph invocation at intake_validation.
    return END


def route_after_data_check(state: dict) -> Union[str, list]:
    all_failed = bool(state.get("sentiment_failed") and state.get("financial_failed") and state.get("macro_failed"))
    if all_failed:
        return ["sentiment_analyst", "financial_analyst", "macro_industry_analyst"]
    return "build_memo"


def build_graph() -> StateGraph:
    register_handler("sentiment_analyst", sentiment_analyst.answer_question)
    register_handler("financial_analyst", financial_analyst.answer_question)
    register_handler("macro_industry_analyst", macro_industry_analyst.answer_question)

    graph = StateGraph(InvestmentResearchState)

    graph.add_node("intake_validation", intake_validation.intake_validation_node)
    graph.add_node("sentiment_analyst", sentiment_analyst.sentiment_analyst_node)
    graph.add_node("financial_analyst", financial_analyst.financial_analyst_node)
    graph.add_node("macro_industry_analyst", macro_industry_analyst.macro_industry_analyst_node)
    graph.add_node("data_failure_check", data_failure_check_node)
    graph.add_node("build_memo", orchestrator.build_memo_node)
    graph.add_node("checkpoint_2_review", orchestrator.checkpoint_2_review_node)

    graph.add_edge(START, "intake_validation")
    graph.add_conditional_edges("intake_validation", route_after_intake)

    # All 3 specialists converge on data_failure_check (LangGraph waits for
    # all parallel branches from this fan-out to complete before running it).
    graph.add_edge("sentiment_analyst", "data_failure_check")
    graph.add_edge("financial_analyst", "data_failure_check")
    graph.add_edge("macro_industry_analyst", "data_failure_check")

    graph.add_conditional_edges("data_failure_check", route_after_data_check)

    graph.add_edge("build_memo", "checkpoint_2_review")
    graph.add_edge("checkpoint_2_review", END)

    return graph


def compile_graph(db_path: str = None):
    """Compile the graph with a SQLite checkpointer (required for interrupt()/Command(resume=...))."""
    conn = sqlite3.connect(db_path or CHECKPOINT_DB, check_same_thread=False)
    checkpointer = SqliteSaver(conn)
    return build_graph().compile(checkpointer=checkpointer)
