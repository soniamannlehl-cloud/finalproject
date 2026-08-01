"""
Company validation node + HITL Checkpoint #1.

The node itself performs no research: it dispatches `company.validate` over
A2A and interprets the result. That separation is the architecture's core
invariant -- the control plane decides, the data plane retrieves.

Checkpoint #1 always interrupts on a resolved match, including an exact
ticker hit. Confirming NVDA looks redundant, but a research run costs real
money and several minutes; a silent mis-resolution that surfaces only in the
final report is far more expensive than one click.
"""

import logging
import uuid

from contracts import TaskState, ValidationStatus
from langgraph.types import interrupt

from ...director.a2a_client import get_a2a_client
from ..state import ResearchState

log = logging.getLogger(__name__)

MAX_VALIDATION_ATTEMPTS = 3


async def validate_company_node(state: ResearchState) -> dict:
    """
    Resolve the user's query to a public company via A2A.

    Returns partial state only -- LangGraph merges it. Every exit path sets
    `validation_status` so the router downstream never has to guess.
    """
    run_id = state["run_id"]
    query = state.get("raw_query", "")
    attempts = state.get("validation_attempts", 0) + 1

    client = get_a2a_client()
    result = await client.dispatch(
        capability="company.validate",
        inputs={"query": query},
        run_id=run_id,
        task_id=f"validate-{uuid.uuid4().hex[:8]}",
        attempt=attempts,
        traceparent=state.get("trace_id"),
    )

    # Transport or provider failure. Deliberately NOT reported as
    # "company not found" -- conflating "we could not look" with "it does
    # not exist" would be a data-integrity bug that misleads the user.
    if result.state == TaskState.FAILED:
        log.warning("validation dispatch failed for run %s: %s", run_id, result.error)
        return {
            "validation_status": None,
            "validation_message": (
                "The company lookup service is unavailable right now, so we could not "
                "verify that company. This is a system issue, not a problem with your input."
            ),
            "validation_attempts": attempts,
            "status": "validation_unavailable",
            "errors": [{"stage": "validate", "error": result.error, "task_id": result.task_id}],
        }

    if not result.evidence:
        return {
            "validation_status": ValidationStatus.NOT_FOUND.value,
            "validation_message": "The lookup returned no result. Try a ticker symbol.",
            "validation_attempts": attempts,
            "status": "validation_failed",
        }

    evidence = result.evidence[0]
    content = evidence.content
    status = content.get("status")

    # Private company or unrecognized input: terminal for this turn. The user
    # starts a new run with different input rather than being trapped in a loop.
    if status in (ValidationStatus.PRIVATE_COMPANY.value, ValidationStatus.NOT_FOUND.value):
        return {
            "validation_status": status,
            "validation_message": content.get("message"),
            "suggested_match": content.get("suggested_match"),
            "validation_attempts": attempts,
            "evidence_ids": [evidence.evidence_id],
            "status": "validation_failed",
        }

    candidates = content.get("candidates", [])
    top = content.get("top_match") or (candidates[0] if candidates else None)
    if not top:
        return {
            "validation_status": ValidationStatus.NOT_FOUND.value,
            "validation_message": "No candidate company could be resolved.",
            "validation_attempts": attempts,
            "status": "validation_failed",
        }

    # ---- HITL Checkpoint #1 ------------------------------------------------
    # interrupt() persists state and suspends. The run resumes on a LATER,
    # SEPARATE HTTP request -- possibly minutes later, possibly against a
    # different worker process -- which is why the Postgres checkpointer is
    # a correctness requirement, not an optimization.
    decision = interrupt(
        {
            "type": "checkpoint_1_company_confirmation",
            "run_id": run_id,
            "query": query,
            "top_match": top,
            "candidates": candidates,
            "exact_ticker_match": content.get("exact_ticker_match", False),
            "prompt": f"Research {top.get('name')} ({top.get('ticker')})?",
            "options": ["confirm", "reject", "select_alternate"],
        }
    )

    return _apply_checkpoint_1_decision(decision, top, candidates, evidence.evidence_id, attempts)


def _apply_checkpoint_1_decision(
    decision, top: dict, candidates: list[dict], evidence_id: str, attempts: int
) -> dict:
    """
    Interpret the human's Checkpoint #1 response.

    Accepts either a bare string ("confirm") or a dict carrying a chosen
    ticker, so the API can stay forgiving about client shape without the
    graph having to care.
    """
    chosen = top
    action = decision

    if isinstance(decision, dict):
        action = decision.get("action", "confirm")
        # The user picked a different candidate from the list.
        if picked := decision.get("ticker"):
            match = next((c for c in candidates if c.get("ticker") == picked), None)
            if match:
                chosen = match

    if isinstance(action, str) and action.strip().lower() in {"confirm", "yes", "y", "true"}:
        return {
            "ticker": chosen.get("ticker"),
            "company_name": chosen.get("name"),
            "sector": chosen.get("sector"),
            "industry": chosen.get("industry"),
            "validation_status": ValidationStatus.RESOLVED.value,
            "validation_message": f"Confirmed {chosen.get('name')} ({chosen.get('ticker')}).",
            "checkpoint_1_confirmed": True,
            "validation_attempts": attempts,
            "evidence_ids": [evidence_id],
            "status": "validated",
        }

    # Rejected: the match was wrong. Ends this turn rather than looping
    # in-node, so the user supplies new input on a fresh run.
    return {
        "validation_status": None,
        "validation_message": "Match rejected. Start a new run with a different company name or ticker.",
        "checkpoint_1_confirmed": False,
        "validation_attempts": attempts,
        "evidence_ids": [evidence_id],
        "status": "validation_rejected",
    }


def route_after_validation(state: ResearchState) -> str:
    """
    Where to go after validation.

    M1 terminates on every path; M2 replaces the "validated" branch with the
    Planner. Kept as a named function so the full transition set is
    enumerable by reading this file.
    """
    if state.get("status") == "validated" and state.get("checkpoint_1_confirmed"):
        return "validated"
    return "stop"
