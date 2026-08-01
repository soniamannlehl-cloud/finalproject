"""
API service entrypoint -- the control plane.

Owns the LangGraph workflow, both human checkpoints, and the Postgres
checkpointer that makes interrupt/resume survive across separate HTTP
requests. It never calls a data provider directly: all research reaches it
through A2A.
"""

import logging
from contextlib import asynccontextmanager

# Tracing MUST be configured before LangGraph modules are imported.
from .config import get_settings
from .observability.langsmith import configure_langsmith

logging.basicConfig(level=get_settings().log_level)
configure_langsmith()

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .api.routes import router as runs_router
from .db import checkpointer as db
from .director.a2a_client import get_a2a_client

log = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    Startup: open the checkpointer, then discover the specialist fleet.

    Discovery failure is logged but non-fatal. The control plane must be able
    to start and report missing capabilities as declared gaps -- refusing to
    boot because a downstream service is slow would make the whole platform
    only as available as its least available part.
    """
    await db.init_checkpointer()

    try:
        index = await get_a2a_client().discover()
        log.info("discovered %d A2A capabilities: %s", len(index), sorted(index))
    except Exception as e:  # noqa: BLE001
        log.warning("A2A discovery failed at startup (will retry on demand): %s", e)

    yield

    await db.close_checkpointer()


app = FastAPI(
    title="AI Investment Research Platform -- API",
    description="Control plane: LangGraph workflow, HITL checkpoints, planning, safety.",
    version="0.1.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(runs_router)


@app.get("/health")
def health() -> dict:
    """
    Liveness + dependency-integrity probe.

    Imports run inside the handler so a broken dependency surfaces as a
    readable failing healthcheck rather than a container that dies before it
    can report why.
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

    try:
        db.get_checkpointer()
        checks["checkpointer"] = "ok"
    except Exception as e:  # noqa: BLE001
        checks["checkpointer"] = f"FAIL: {e}"
        healthy = False

    return {
        "status": "healthy" if healthy else "unhealthy",
        "service": settings.service_name,
        "role": "control-plane",
        "checks": checks,
    }


@app.get("/capabilities")
async def capabilities() -> dict:
    """Which A2A capabilities are currently discoverable -- useful for debugging the fleet."""
    client = get_a2a_client()
    index = await client.discover(force=True)
    return {
        "capabilities": sorted(index),
        "count": len(index),
        "agents": {cap: agent for cap, (agent, _) in index.items()},
    }


@app.get("/")
def root() -> dict:
    return {
        "service": "AI Investment Research Platform -- API",
        "role": "control-plane",
        "docs": "/docs",
        "health": "/health",
        "runs": "/runs",
    }
