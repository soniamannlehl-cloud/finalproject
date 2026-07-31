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
from ..evidence import repository as evidence_repo
from ..graph.builder import compile_graph
from ..graph.state import initial_state
from ..thesis import repository as thesis_repo

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


@router.get("/{run_id}/evidence")
async def get_run_evidence(run_id: str) -> dict:
    """
    All evidence gathered, with citations.

    This is what makes every downstream claim auditable: the report cites
    evidence IDs, and this endpoint resolves them back to source, timestamp,
    and confidence.
    """
    if await db.get_run(run_id) is None:
        raise HTTPException(status_code=404, detail=f"run {run_id} not found")

    records = await evidence_repo.get_evidence_for_run(run_id)
    return {
        "run_id": run_id,
        "count": len(records),
        "by_capability": await evidence_repo.evidence_summary(run_id),
        "evidence": [
            {
                "evidence_id": r["evidence_id"],
                "capability": r["capability"],
                "agent_id": r["agent_id"],
                "source_type": r["source_type"],
                "source_name": r["source_name"],
                "source_url": r["source_url"],
                "citation": r["citation"],
                "summary": r["summary"],
                "confidence": r["confidence"],
                "provider_degraded": r["provider_degraded"],
                "retrieved_at": r["retrieved_at"],
            }
            for r in records
        ],
    }


@router.get("/{run_id}/safety")
async def get_run_safety(run_id: str) -> dict:
    """
    The safety verdict, including what was NOT checked.

    `semantic_verified` is reported explicitly because an unverified run must
    not be mistaken for a clean one: a pipeline that returns green having
    examined nothing manufactures false assurance.
    """
    run = await db.get_run(run_id)
    if run is None:
        raise HTTPException(status_code=404, detail=f"run {run_id} not found")

    app_graph = compile_graph(db.get_checkpointer())
    snapshot = await app_graph.aget_state({"configurable": {"thread_id": run["thread_id"]}})
    report = (snapshot.values or {}).get("safety_report")

    if report is None:
        return {
            "run_id": run_id,
            "status": "safety pipeline has not run for this run yet",
            "safety_report": None,
        }

    findings = report.get("findings", [])
    by_severity: dict[str, int] = {}
    for f in findings:
        by_severity[f["severity"]] = by_severity.get(f["severity"], 0) + 1

    not_run = [f for f in findings if f["check_name"].endswith("_not_run")]

    return {
        "run_id": run_id,
        "evidence_score": report["evidence_score"],
        "coverage_ratio": round(
            len(report["coverage"]["satisfied_capabilities"])
            / max(1, len(report["coverage"]["required_capabilities"])), 3
        ),
        "is_blocking": bool(
            report.get("unsupported_claim_ids")
            or any(f["severity"] == "blocking" for f in findings)
        ),
        "semantic_verified": len(not_run) == 0,
        "checks_not_run": [f["message"] for f in not_run],
        "unsupported_claim_ids": report.get("unsupported_claim_ids", []),
        "stale_evidence_count": len(report.get("stale_evidence_ids", [])),
        "contradiction_count": report.get("contradiction_count", 0),
        "findings_by_severity": by_severity,
        "findings": findings,
        "coverage": report["coverage"],
    }


@router.get("/{run_id}/thesis")
async def get_run_thesis(run_id: str) -> dict:
    """
    The thesis and its full revision history.

    Returns every version rather than only the current one, because the
    platform's claim is that the thesis EVOLVES as evidence arrives -- and
    that is only demonstrable by showing the trajectory.
    """
    if await db.get_run(run_id) is None:
        raise HTTPException(status_code=404, detail=f"run {run_id} not found")

    history = await thesis_repo.get_history(run_id)
    current = history.current

    return {
        "run_id": run_id,
        "version_count": len(history.versions),
        "current": current.model_dump(mode="json") if current else None,
        "confidence_trajectory": history.confidence_trajectory(),
        "history": [
            {
                "version": v.version,
                "parent_version": v.parent_version,
                "stance": v.stance.value,
                "confidence": v.confidence,
                "statement": v.statement,
                "change_reason": v.change_reason,
                "triggered_by": v.triggered_by,
                "supporting_count": len(v.supporting_claim_ids),
                "contradicting_count": len(v.contradicting_claim_ids),
                "created_at": v.created_at,
            }
            for v in history.versions
        ],
    }
