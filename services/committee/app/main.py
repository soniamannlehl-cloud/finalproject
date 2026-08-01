"""
Committee service entrypoint -- deliberation.

Exposes an A2A-compatible task endpoint so the control plane can dispatch
committee deliberation without importing CrewAI into the LangGraph service.
"""

import logging
import time
from datetime import datetime, timezone

from contracts import TaskState
from fastapi import FastAPI
from pydantic import BaseModel, Field

from .config import get_settings
from .crew.brief import EvidenceBrief
from .crew.committee import run_committee

logging.basicConfig(level=get_settings().log_level)
log = logging.getLogger(__name__)

app = FastAPI(
    title="AI Investment Research Platform -- Committee",
    description="Deliberation: CrewAI investment committee (Bull / Bear / CIO).",
    version="0.1.0",
)


class CommitteeTaskRequest(BaseModel):
    """A2A-compatible request envelope for committee deliberation."""

    task_id: str
    run_id: str
    capability: str = "committee.deliberate"
    inputs: dict = Field(default_factory=dict)
    traceparent: str | None = None


@app.get("/health")
def health() -> dict:
    """
    Liveness + dependency-integrity probe.

    The `crewai` check is the one that matters architecturally: it confirms
    CrewAI resolved cleanly in an environment with no LangGraph present.
    """
    settings = get_settings()
    checks: dict[str, str] = {}
    healthy = True

    try:
        import contracts

        checks["contracts"] = f"ok ({contracts.__version__})"
    except Exception as e:  # noqa: BLE001
        checks["contracts"] = f"FAIL: {e}"
        healthy = False

    try:
        from crewai import Agent, Crew, Task  # noqa: F401

        checks["crewai"] = "ok"
    except Exception as e:  # noqa: BLE001
        checks["crewai"] = f"FAIL: {e}"
        healthy = False

    # Asserting absence, not presence: if LangGraph is importable here, the
    # isolation boundary has been violated and the conflict risk is back.
    try:
        import langgraph  # noqa: F401

        checks["isolation"] = "WARNING: langgraph present in committee env"
    except ImportError:
        checks["isolation"] = "ok (langgraph correctly absent)"

    return {
        "status": "healthy" if healthy else "unhealthy",
        "service": settings.service_name,
        "role": "deliberation",
        "checks": checks,
    }


@app.get("/")
def root() -> dict:
    return {
        "service": "AI Investment Research Platform -- Committee",
        "role": "deliberation",
        "health": "/health",
        "a2a_tasks": "/a2a/tasks",
    }


@app.post("/a2a/tasks")
def execute_committee_task(request: CommitteeTaskRequest) -> dict:
    """
    Convene the investment committee on a condensed evidence brief.

    Never raises: failures return state=FAILED inside the response body so
    the control plane can degrade gracefully.
    """
    started = datetime.now(timezone.utc)
    t0 = time.perf_counter()

    if request.capability != "committee.deliberate":
        return {
            "task_id": request.task_id,
            "run_id": request.run_id,
            "state": TaskState.FAILED.value,
            "error": f"unsupported capability '{request.capability}'",
            "started_at": started.isoformat(),
            "latency_ms": int((time.perf_counter() - t0) * 1000),
        }

    brief_data = request.inputs.get("brief")
    if not brief_data:
        return {
            "task_id": request.task_id,
            "run_id": request.run_id,
            "state": TaskState.FAILED.value,
            "error": "missing 'brief' in inputs",
            "started_at": started.isoformat(),
            "latency_ms": int((time.perf_counter() - t0) * 1000),
        }

    settings = get_settings()
    if not settings.openai_api_key:
        return {
            "task_id": request.task_id,
            "run_id": request.run_id,
            "state": TaskState.FAILED.value,
            "error": "OPENAI_API_KEY not configured for committee service",
            "action": "insufficient_evidence",
            "confidence": 0.0,
            "cio_rationale": "Committee cannot deliberate without an LLM API key.",
            "started_at": started.isoformat(),
            "latency_ms": int((time.perf_counter() - t0) * 1000),
        }

    try:
        brief = EvidenceBrief.model_validate(brief_data)
        result = run_committee(brief)
        result.update({
            "task_id": request.task_id,
            "run_id": request.run_id,
            "state": TaskState.SUCCEEDED.value,
            "started_at": started.isoformat(),
            "latency_ms": int((time.perf_counter() - t0) * 1000),
        })
        return result
    except Exception as e:  # noqa: BLE001
        log.exception("committee deliberation failed for run %s", request.run_id)
        return {
            "task_id": request.task_id,
            "run_id": request.run_id,
            "state": TaskState.FAILED.value,
            "error": str(e),
            "action": "insufficient_evidence",
            "confidence": 0.0,
            "cio_rationale": f"Committee deliberation failed: {e}",
            "started_at": started.isoformat(),
            "latency_ms": int((time.perf_counter() - t0) * 1000),
        }
