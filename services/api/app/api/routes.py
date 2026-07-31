"""
REST API.

The endpoints mirror the workflow's shape: a run is *started*, may *pause*
at a human checkpoint, and is *resumed* by a separate later request. That
separation is why every response carries the interrupt payload explicitly --
a client must be able to render the pending decision without holding any
server-side session.
"""

import logging
import uuid

from fastapi import APIRouter, HTTPException
from langgraph.types import Command
from pydantic import BaseModel, Field

from ..db import checkpointer as db
from ..graph.builder import compile_graph
from ..graph.state import initial_state

log = logging.getLogger(__name__)
router = APIRouter(prefix="/runs", tags=["runs"])


class StartRunRequest(BaseModel):
    query: str = Field(min_length=1, description="Company name or ticker, e.g. 'NVDA'")


class ResumeRequest(BaseModel):
    """
    A human's answer to a checkpoint.

    `action` is free-form so one endpoint serves both checkpoints:
    "confirm"/"reject" at #1, "approve"/"reject"/"request_analysis" at #2.
    """

    action: str = Field(description="confirm | reject | select_alternate | approve | ...")
    ticker: str | None = Field(default=None, description="When selecting an alternate candidate")
    feedback: str | None = Field(default=None, description="Free-text feedback (checkpoint #2)")


def _interrupt_payload(result: dict) -> dict | None:
    """
    Extract the pending human decision from a graph result.

    LangGraph returns interrupts under `__interrupt__`; the client needs the
    payload, not the framework's envelope.
    """
    interrupts = result.get("__interrupt__")
    if not interrupts:
        return None
    first = interrupts[0]
    return getattr(first, "value", first)


def _public_state(state: dict) -> dict:
    """Project internal state to what a client needs, omitting graph plumbing."""
    return {
        "run_id": state.get("run_id"),
        "query": state.get("raw_query"),
        "ticker": state.get("ticker"),
        "company_name": state.get("company_name"),
        "sector": state.get("sector"),
        "industry": state.get("industry"),
        "status": state.get("status"),
        "validation_status": state.get("validation_status"),
        "message": state.get("validation_message"),
        "evidence_count": len(state.get("evidence_ids", [])),
        "errors": state.get("errors", []),
    }


@router.post("", status_code=201)
async def start_run(request: StartRunRequest) -> dict:
    """
    Begin a research run.

    Returns as soon as the workflow hits its first human checkpoint. The
    response carries `awaiting_human` plus the interrupt payload, so the
    client can render the decision immediately.
    """
    run_id = f"run_{uuid.uuid4().hex[:12]}"
    thread_id = run_id  # one checkpoint thread per run

    await db.create_run(run_id, thread_id, request.query, "validating")

    app_graph = compile_graph(db.get_checkpointer())
    config = {"configurable": {"thread_id": thread_id}}

    try:
        result = await app_graph.ainvoke(initial_state(run_id, request.query), config)
    except Exception as e:  # noqa: BLE001
        log.exception("run %s failed to start", run_id)
        await db.update_run(run_id, status="error", completed=True)
        raise HTTPException(status_code=500, detail=f"workflow error: {e}") from e

    interrupt = _interrupt_payload(result)
    status = "awaiting_human" if interrupt else result.get("status", "unknown")
    await db.update_run(run_id, status=status)

    return {
        "run_id": run_id,
        "awaiting_human": interrupt is not None,
        "checkpoint": interrupt,
        "state": _public_state(result),
    }


@router.post("/{run_id}/resume")
async def resume_run(run_id: str, request: ResumeRequest) -> dict:
    """
    Resume a paused run with a human decision.

    This is a fresh HTTP request with no memory of the one that started the
    run -- the graph's position and state come entirely from the Postgres
    checkpoint keyed by thread_id.
    """
    run = await db.get_run(run_id)
    if run is None:
        raise HTTPException(status_code=404, detail=f"run {run_id} not found")

    app_graph = compile_graph(db.get_checkpointer())
    config = {"configurable": {"thread_id": run["thread_id"]}}

    snapshot = await app_graph.aget_state(config)
    if not snapshot.next:
        raise HTTPException(
            status_code=409,
            detail=f"run {run_id} is not paused (status: {run['status']})",
        )

    resume_value = {
        "action": request.action,
        "ticker": request.ticker,
        "feedback": request.feedback,
    }

    try:
        result = await app_graph.ainvoke(Command(resume=resume_value), config)
    except Exception as e:  # noqa: BLE001
        log.exception("run %s failed to resume", run_id)
        raise HTTPException(status_code=500, detail=f"workflow error: {e}") from e

    interrupt = _interrupt_payload(result)
    status = "awaiting_human" if interrupt else result.get("status", "complete")
    terminal = interrupt is None

    await db.update_run(
        run_id,
        status=status,
        ticker=result.get("ticker"),
        company_name=result.get("company_name"),
        completed=terminal,
    )

    return {
        "run_id": run_id,
        "awaiting_human": interrupt is not None,
        "checkpoint": interrupt,
        "state": _public_state(result),
    }


@router.get("/{run_id}")
async def get_run_status(run_id: str) -> dict:
    """Current status, including any pending checkpoint, reconstructed from the checkpoint store."""
    run = await db.get_run(run_id)
    if run is None:
        raise HTTPException(status_code=404, detail=f"run {run_id} not found")

    app_graph = compile_graph(db.get_checkpointer())
    config = {"configurable": {"thread_id": run["thread_id"]}}
    snapshot = await app_graph.aget_state(config)

    pending = None
    if snapshot.next and snapshot.tasks:
        for task in snapshot.tasks:
            if task.interrupts:
                pending = getattr(task.interrupts[0], "value", None)
                break

    return {
        "run_id": run_id,
        "status": run["status"],
        "created_at": run["created_at"],
        "completed_at": run["completed_at"],
        "awaiting_human": bool(snapshot.next),
        "checkpoint": pending,
        "state": _public_state(snapshot.values or {}),
    }


@router.get("")
async def list_recent_runs(limit: int = 20) -> dict:
    runs = await db.list_runs(limit)
    return {"runs": runs, "count": len(runs)}
