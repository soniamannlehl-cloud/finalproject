"""
Committee service entrypoint -- deliberation.

Milestone 0 scope: boot, expose health, and confirm CrewAI imports in an
environment quarantined from LangGraph. The Bull/Bear/CIO crew lands in M6.
"""

import logging

from fastapi import FastAPI

from .config import get_settings

logging.basicConfig(level=get_settings().log_level)
log = logging.getLogger(__name__)

app = FastAPI(
    title="AI Investment Research Platform -- Committee",
    description="Deliberation: CrewAI investment committee (Bull / Bear / CIO).",
    version="0.1.0",
)


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
    }
