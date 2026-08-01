"""
LangGraph workflow state.

TWO RULES GOVERN THIS MODULE.

Rule 1 -- any field that parallel branches write MUST have a reducer.
LangGraph raises `InvalidUpdateError: Can receive only one value per step`
when two concurrent nodes write the same un-reduced key. M1 has no fan-out
yet, but the reducers are declared now because retrofitting them after nine
specialists are dispatching concurrently means debugging a failure that only
appears under parallelism.

Rule 2 -- state is a manifest, not a warehouse.
LangGraph checkpoints this entire object on every superstep. Evidence
payloads, filing text, and committee transcripts live in Postgres; state
carries only IDs pointing at them. Violating this produces multi-megabyte
checkpoints and visibly slow resume.

Fields written by exactly one node each (`ticker`, `validation_status`, ...)
are deliberately left un-reduced. That is a maintained invariant: if a field
below ever gains a second writer, it needs a reducer at the same time.
"""

import operator
from typing import Annotated, Any, TypedDict


def merge_dicts(left: dict | None, right: dict | None) -> dict:
    """
    Shallow dict merge for concurrent keyed writes (right wins on conflict).

    Used for `task_status`, where each parallel specialist branch writes only
    its own task_id -- so in practice keys never collide and the merge is
    purely additive.
    """
    return {**(left or {}), **(right or {})}


def keep_last(left: Any, right: Any) -> Any:
    """
    Last-write-wins for a field that is normally single-writer but may be
    touched on a replan pass. Explicit so the intent is visible at the
    field, rather than relying on LangGraph's default overwrite.
    """
    return right if right is not None else left


class ResearchState(TypedDict, total=False):
    """
    The workflow's shared state.

    `total=False` because the graph populates this incrementally: a run
    interrupted at HITL #1 has no plan, no evidence, and no recommendation.
    """

    # --- identity -----------------------------------------------------------
    run_id: str
    raw_query: str          # exactly as the user typed it
    ticker: str | None
    company_name: str | None

    # --- validation / HITL #1 -----------------------------------------------
    validation_status: str | None      # contracts.ValidationStatus
    validation_message: str | None     # user-facing explanation
    candidates: list[dict]             # candidate companies awaiting confirmation
    checkpoint_1_confirmed: bool | None
    validation_attempts: int           # bounds the reject -> retry loop

    # --- classification (M2) ------------------------------------------------
    sector: str | None
    industry: str | None
    classification: str | None         # contracts.IndustryPlaybook

    # --- planning (M2) ------------------------------------------------------
    plan: dict | None                  # serialized ResearchPlan
    plan_revision: int

    # --- research execution (M3) -------------------------------------------
    # WRITTEN BY PARALLEL BRANCHES -- reducers are mandatory here.
    evidence_ids: Annotated[list[str], operator.add]
    claim_ids: Annotated[list[str], operator.add]
    task_status: Annotated[dict, merge_dicts]
    errors: Annotated[list[dict], operator.add]

    # --- thesis (M4) --------------------------------------------------------
    thesis_version: Annotated[int | None, keep_last]
    thesis_stance: Annotated[str | None, keep_last]
    thesis_confidence: Annotated[float | None, keep_last]
    thesis_framework: Annotated[dict | None, keep_last]
    industry_profile: Annotated[dict | None, keep_last]

    # --- safety (M5) --------------------------------------------------------
    safety_report: dict | None
    evidence_score: float | None

    # --- committee + HITL #2 (M6/M7) ---------------------------------------
    committee_proposal: dict | None
    recommendation: dict | None
    committee_decision: str | None     # contracts.HumanDecision
    committee_feedback: str | None
    replan_rounds: int

    # --- output (M8) --------------------------------------------------------
    report_id: str | None

    # --- control flow -------------------------------------------------------
    status: str
    trace_id: str | None               # propagated to specialists as traceparent


def initial_state(run_id: str, raw_query: str, trace_id: str | None = None) -> ResearchState:
    """
    Build a fresh state for a new run.

    Counters start at zero rather than being absent so the loop-bound checks
    (`validation_attempts`, `replan_rounds`) never have to guard against None.
    """
    return ResearchState(
        run_id=run_id,
        raw_query=raw_query,
        ticker=None,
        company_name=None,
        validation_status=None,
        validation_message=None,
        candidates=[],
        checkpoint_1_confirmed=None,
        validation_attempts=0,
        sector=None,
        industry=None,
        classification=None,
        plan=None,
        plan_revision=0,
        evidence_ids=[],
        claim_ids=[],
        task_status={},
        errors=[],
        thesis_version=None,
        thesis_stance=None,
        thesis_confidence=None,
        thesis_framework=None,
        industry_profile=None,
        safety_report=None,
        evidence_score=None,
        committee_proposal=None,
        recommendation=None,
        committee_decision=None,
        committee_feedback=None,
        replan_rounds=0,
        report_id=None,
        status="validating",
        trace_id=trace_id,
    )
