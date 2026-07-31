"""
API service entrypoint -- the control plane.

Milestone 0 scope: boot, expose health, and prove this container's
dependency tree (LangGraph + langchain-core) resolves and coexists with
the shared contracts package. Workflow nodes arrive in M1+.
"""

import logging

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .config import get_settings

logging.basicConfig(level=get_settings().log_level)
log = logging.getLogger(__name__)

app = FastAPI(
    title="AI Investment Research Platform -- API",
    description="Control plane: LangGraph workflow, HITL checkpoints, planning, safety.",
    version="0.1.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/health")
def health() -> dict:
    """
    Liveness + dependency-integrity probe.

    Imports are performed inside the handler rather than at module scope so
    a broken dependency surfaces as a failing healthcheck with a readable
    reason, instead of a container that dies before it can report anything.
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
        import langgraph
        from langgraph.graph import StateGraph  # noqa: F401

        checks["langgraph"] = "ok"
    except Exception as e:  # noqa: BLE001
        checks["langgraph"] = f"FAIL: {e}"
        healthy = False

    try:
        import langchain_core

        checks["langchain_core"] = f"ok ({langchain_core.__version__})"
    except Exception as e:  # noqa: BLE001
        checks["langchain_core"] = f"FAIL: {e}"
        healthy = False

    return {
        "status": "healthy" if healthy else "unhealthy",
        "service": settings.service_name,
        "role": "control-plane",
        "checks": checks,
    }


@app.get("/")
def root() -> dict:
    return {
        "service": "AI Investment Research Platform -- API",
        "role": "control-plane",
        "docs": "/docs",
        "health": "/health",
    }
