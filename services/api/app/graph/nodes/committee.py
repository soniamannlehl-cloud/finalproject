"""
Investment committee node.

Dispatches a condensed evidence brief to the CrewAI service over HTTP.
The committee proposes a recommendation; the synthesizer node applies the
deterministic policy gate before anything reaches the human reviewer.
"""

import logging

from contracts import TaskState

from ...committee.brief_builder import build_brief_payload
from ...committee.client import get_committee_client

log = logging.getLogger(__name__)


async def committee_node(state: dict) -> dict:
    """Convene the Bull/Bear/CIO debate via the committee service."""
    run_id = state["run_id"]

    try:
        brief = await build_brief_payload(state)
    except Exception as e:  # noqa: BLE001
        log.exception("failed to build committee brief for run %s", run_id)
        return {
            "status": "committee_failed",
            "errors": [{"stage": "committee", "error": f"brief assembly failed: {e}"}],
            "recommendation": None,
        }

    client = get_committee_client()
    result = await client.deliberate(
        brief=brief,
        run_id=run_id,
        traceparent=state.get("trace_id"),
    )

    if result.get("state") == TaskState.FAILED.value:
        log.warning("committee failed for run %s: %s", run_id, result.get("error"))
        return {
            "status": "committee_degraded",
            "errors": [{"stage": "committee", "error": result.get("error", "unknown")}],
            "committee_proposal": result,
        }

    log.info(
        "run %s committee proposed: %s (confidence %.2f)",
        run_id, result.get("action"), result.get("confidence", 0.0),
    )
    return {
        "committee_proposal": result,
        "status": "committee_complete",
    }
