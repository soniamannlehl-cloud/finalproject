"""
Specialists service entrypoint -- the data plane.

Milestone 0 scope: boot, expose health, and serve a placeholder agent
discovery endpoint. The nine specialist agents and their AgentCards arrive
in M2/M3; the discovery route exists now so the Director's contract is
fixed from the start.
"""

import logging

from fastapi import FastAPI

from .config import get_settings

logging.basicConfig(level=get_settings().log_level)
log = logging.getLogger(__name__)

app = FastAPI(
    title="AI Investment Research Platform -- Specialists",
    description="Data plane: research agents exposed over A2A.",
    version="0.1.0",
)


@app.get("/health")
def health() -> dict:
    """Liveness + dependency-integrity probe (see api service for rationale)."""
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
        import a2a  # noqa: F401

        checks["a2a_sdk"] = "ok"
    except Exception as e:  # noqa: BLE001
        checks["a2a_sdk"] = f"FAIL: {e}"
        healthy = False

    try:
        import yfinance  # noqa: F401

        checks["yfinance"] = "ok"
    except Exception as e:  # noqa: BLE001
        checks["yfinance"] = f"FAIL: {e}"
        healthy = False

    return {
        "status": "healthy" if healthy else "unhealthy",
        "service": settings.service_name,
        "role": "data-plane",
        "checks": checks,
    }


@app.get("/agents")
def list_agents() -> dict:
    """
    A2A discovery endpoint.

    The Research Director calls this at startup to build its capability ->
    endpoint index. Returns an empty fleet in M0; populated in M2.
    """
    return {"agents": [], "count": 0, "note": "specialist fleet lands in M2"}


@app.get("/")
def root() -> dict:
    return {
        "service": "AI Investment Research Platform -- Specialists",
        "role": "data-plane",
        "discovery": "/agents",
        "health": "/health",
    }
