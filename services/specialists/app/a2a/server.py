"""
A2A server -- how the control plane reaches the specialist fleet.

Exposes three things:
  GET  /.well-known/agent.json   primary AgentCard (A2A discovery convention)
  GET  /a2a/agents               all cards published by this service
  POST /a2a/tasks                execute one capability

Design rule enforced here: a task that fails returns HTTP 200 with
`state=FAILED` inside the A2ATaskResult, not an HTTP error. The Director
must be able to distinguish "the agent ran and could not find data" from
"the transport broke", and it must be able to record either as evidence of
a degraded run rather than crashing the workflow.
"""

import logging
import time
from datetime import datetime, timezone

from fastapi import APIRouter
from contracts import A2ATaskRequest, A2ATaskResult, TaskState

from ..config import get_settings
from . import cards

log = logging.getLogger(__name__)
router = APIRouter()


@router.get("/.well-known/agent.json")
def well_known_agent_card() -> dict:
    """
    A2A discovery convention: an agent's card lives at a well-known path.

    This service hosts several agents, so it publishes the first as the
    primary card and the full fleet at /a2a/agents.
    """
    settings = get_settings()
    primary = next(iter(cards.AGENT_CAPABILITIES))
    return cards.card_to_dict(cards.build_agent_card(primary, settings.public_base_url))


@router.get("/a2a/agents")
def list_agent_cards() -> dict:
    """Full fleet discovery -- the Director builds its capability index from this."""
    settings = get_settings()
    fleet = cards.all_agent_cards(settings.public_base_url)
    return {
        "agents": fleet,
        "count": len(fleet),
        "capabilities": cards.served_capabilities(),
    }


@router.post("/a2a/tasks", response_model=A2ATaskResult)
def execute_task(request: A2ATaskRequest) -> A2ATaskResult:
    """
    Execute one capability and return evidence.

    Never raises: every failure path produces a well-formed A2ATaskResult so
    the Director always receives structured information it can act on.
    """
    started = datetime.now(timezone.utc)
    t0 = time.perf_counter()

    def _finish(
        state: TaskState,
        *,
        evidence=None,
        confidence: float = 0.0,
        error: str | None = None,
        degraded: str | None = None,
        agent_id: str = "unknown",
    ) -> A2ATaskResult:
        return A2ATaskResult(
            task_id=request.task_id,
            run_id=request.run_id,
            agent_id=agent_id,
            capability=request.capability,
            state=state,
            evidence=evidence or [],
            confidence=confidence,
            error=error,
            degraded_reason=degraded,
            providers_used=["yfinance"] if state != TaskState.FAILED else [],
            started_at=started,
            completed_at=datetime.now(timezone.utc),
            latency_ms=int((time.perf_counter() - t0) * 1000),
        )

    handler = cards.resolve_handler(request.capability)
    if handler is None:
        log.warning("unserviceable capability requested: %s", request.capability)
        return _finish(
            TaskState.FAILED,
            error=(
                f"No agent in this service serves capability '{request.capability}'. "
                f"Available: {cards.served_capabilities()}"
            ),
        )

    agent_id = next(
        (aid for aid, caps in cards.AGENT_CAPABILITIES.items() if request.capability in caps),
        "unknown",
    )

    try:
        evidence, confidence, degraded = handler(request.inputs, request.run_id, request.task_id)
    except ValueError as e:
        # Bad inputs -- retrying identical inputs cannot help.
        log.warning("invalid inputs for %s: %s", request.capability, e)
        return _finish(TaskState.FAILED, error=f"invalid inputs: {e}", agent_id=agent_id)
    except Exception as e:  # noqa: BLE001
        # Provider/transport failure -- genuinely retriable, so surface it as
        # FAILED and let the Director decide.
        log.exception("capability %s failed", request.capability)
        return _finish(TaskState.FAILED, error=str(e), agent_id=agent_id)

    state = TaskState.DEGRADED if degraded else TaskState.SUCCEEDED
    return _finish(
        state,
        evidence=evidence,
        confidence=confidence,
        degraded=degraded,
        agent_id=agent_id,
    )
