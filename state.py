"""
state.py

Defines the shared state object that flows through every node in the
Collaborative Investment Research Platform LangGraph.

Every agent (Intake & Validation, Sentiment Analyst, Financial Analyst,
Macro & Industry Analyst, Orchestrator) reads from and writes to this
single state object. LangGraph merges each node's returned dict into
this state automatically.
"""

from typing import TypedDict, Literal, Optional
from langgraph.graph import MessagesState


class InvestmentResearchState(MessagesState):
    """
    Extends LangGraph's MessagesState (which already gives us a `messages`
    field for conversation history) with all the fields our 5 agents need.
    """

    # ------------------------------------------------------------------
    # User input / Intake & Validation Agent
    # ------------------------------------------------------------------
    raw_user_input: str
    intake_status: Literal["confirmed", "private_company", "not_found", "pending"]
    company_name: Optional[str]
    ticker: Optional[str]

    # ------------------------------------------------------------------
    # Industry Identification (deterministic lookup, not an agent)
    # ------------------------------------------------------------------
    industry: Optional[str]
    sector: Optional[str]

    # ------------------------------------------------------------------
    # Sentiment Analyst Agent output
    # ------------------------------------------------------------------
    sentiment_summary: Optional[str]
    key_articles: Optional[list]
    sentiment_trend: Optional[str]
    sentiment_data_as_of: Optional[str]
    sentiment_failed: bool

    # ------------------------------------------------------------------
    # Financial Analyst Agent output
    # ------------------------------------------------------------------
    raw_financials: Optional[dict]
    universal_ratios: Optional[dict]
    industry_ratios: Optional[dict]
    ratio_interpretation: Optional[str]
    financial_data_as_of: Optional[str]
    financial_failed: bool

    # ------------------------------------------------------------------
    # Macro & Industry Analyst Agent output
    # ------------------------------------------------------------------
    macro_indicators: Optional[dict]        # {current, trend}
    sector_performance: Optional[dict]      # {current, trend, vs_sp500}
    industry_landscape: Optional[dict]      # {competitive_summary, notable_developments, key_sources}
    macro_interpretation: Optional[str]
    macro_data_as_of: Optional[str]
    macro_failed: bool

    # ------------------------------------------------------------------
    # Orchestrator Agent / Memo
    # ------------------------------------------------------------------
    headline_finding: Optional[str]
    thesis_summary: Optional[str]
    evidence_by_category: Optional[dict]
    reasoning_chain: Optional[list]         # explicit decomposition steps (planning requirement)
    risk_factors: Optional[list]
    invalidation_triggers: Optional[list]
    evidence_pattern_classification: Optional[str]
    data_gaps: Optional[list]               # which specialists failed, flagged transparently

    # Draft investment recommendation -- a directional analyst-style thesis
    # conclusion (e.g. "constructive", "cautious", "neutral" + rationale),
    # drafted FOR the investment committee's review, never surfaced to an
    # end investor until Checkpoint #2 approves it. Regenerated on each
    # revision round to incorporate committee_feedback (thesis update as
    # new input arrives).
    draft_recommendation: Optional[str]
    revision_count: Optional[int]

    # ------------------------------------------------------------------
    # HITL checkpoints / Q&A / Committee approval
    # ------------------------------------------------------------------
    checkpoint_1_approved: Optional[bool]
    checkpoint_2_qa_history: Optional[list]   # [{question, routed_to_agent, answer}, ...]
    committee_decision: Optional[Literal["approved", "rejected", "revise"]]
    committee_feedback: Optional[str]         # revision instructions, or documented rationale
    user_takeaway: Optional[str]

    # ------------------------------------------------------------------
    # Control flow
    # ------------------------------------------------------------------
    status: Literal[
        "intake",
        "researching",
        "data_failure_check",
        "synthesizing",
        "review",
        "qa",
        "complete",
    ]


def get_initial_state(raw_user_input: str) -> dict:
    """
    Helper to build a fresh state dict when a new research session starts.
    Only sets the fields we know at t=0; everything else defaults to None/False
    so downstream nodes can safely check `if state.get("sentiment_failed")` etc.
    """
    return {
        "raw_user_input": raw_user_input,
        "intake_status": "pending",
        "company_name": None,
        "ticker": None,
        "industry": None,
        "sector": None,
        "sentiment_summary": None,
        "key_articles": None,
        "sentiment_trend": None,
        "sentiment_data_as_of": None,
        "sentiment_failed": False,
        "raw_financials": None,
        "universal_ratios": None,
        "industry_ratios": None,
        "ratio_interpretation": None,
        "financial_data_as_of": None,
        "financial_failed": False,
        "macro_indicators": None,
        "sector_performance": None,
        "industry_landscape": None,
        "macro_interpretation": None,
        "macro_data_as_of": None,
        "macro_failed": False,
        "headline_finding": None,
        "thesis_summary": None,
        "evidence_by_category": None,
        "reasoning_chain": None,
        "risk_factors": None,
        "invalidation_triggers": None,
        "evidence_pattern_classification": None,
        "data_gaps": None,
        "draft_recommendation": None,
        "revision_count": 0,
        "checkpoint_1_approved": None,
        "checkpoint_2_qa_history": [],
        "committee_decision": None,
        "committee_feedback": None,
        "user_takeaway": None,
        "status": "intake",
    }
