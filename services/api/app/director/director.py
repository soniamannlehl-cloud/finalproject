"""
Research Director.

The orchestrator. It assigns work, monitors execution, records failures, and
merges results -- and it never performs research itself. That boundary is
what keeps the system debuggable: every external call originates from a
specialist, and every scheduling decision originates here.

Parallelism comes from LangGraph's `Send` API, not from graph topology. The
Director reads `plan.execution_layers()` and emits one `Send` per task in
the current layer, all targeting the same `specialist_proxy` node. The graph
stays static and checkpointable while the fan-out width is decided at
runtime from the plan -- which is how dynamic dispatch is achieved without
rebuilding the graph per request.
"""

import logging
from datetime import datetime, timezone

from contracts import Criticality, ResearchPlan, TaskState
from langgraph.types import Send

from ..evidence import repository
from .a2a_client import get_a2a_client

log = logging.getLogger(__name__)


def _completed_task_ids(task_status: dict) -> set[str]:
    return {
        tid for tid, info in (task_status or {}).items()
        if info.get("state") in (TaskState.SUCCEEDED.value, TaskState.DEGRADED.value)
    }


def _finished_task_ids(task_status: dict) -> set[str]:
    """Finished includes failures -- a failed dependency must not block forever."""
    return set((task_status or {}).keys())


def next_dispatch_layer(plan: ResearchPlan, task_status: dict) -> list:
    """
    Tasks whose dependencies are satisfied and which have not yet run.

    Depends on COMPLETED (not merely finished) predecessors: a task whose
    dependency failed is skipped rather than run against missing inputs,
    because analysis built on absent data is worse than a declared gap.
    """
    completed = _completed_task_ids(task_status)
    finished = _finished_task_ids(task_status)

    return [
        task for task in plan.tasks
        if task.task_id not in finished and set(task.depends_on) <= completed
    ]


def blocked_task_ids(plan: ResearchPlan, task_status: dict) -> list[str]:
    """Tasks that can never run because a dependency failed."""
    completed = _completed_task_ids(task_status)
    finished = _finished_task_ids(task_status)

    blocked = []
    for task in plan.tasks:
        if task.task_id in finished:
            continue
        unmet = set(task.depends_on) - completed
        if unmet and unmet <= finished:  # deps finished but didn't succeed
            blocked.append(task.task_id)
    return blocked


async def director_node(state: dict) -> dict:
    """
    Decide what to dispatch next.

    Runs once per execution layer: the graph loops back here after each
    parallel batch completes, so a 3-layer plan passes through the Director
    three times. Recording declared gaps here (rather than at report time)
    means the shortfall is visible in state the moment it happens.
    """
    plan_data = state.get("plan")
    if not plan_data:
        return {"status": "dispatch_failed",
                "errors": [{"stage": "director", "error": "no plan in state"}]}

    plan = ResearchPlan.model_validate(plan_data)
    task_status = state.get("task_status", {})

    # Capabilities no agent advertises. Reported as declared gaps rather than
    # dispatched into a guaranteed failure.
    client = get_a2a_client()
    unserviceable = await client.missing({t.capability for t in plan.tasks})

    pending = [t for t in next_dispatch_layer(plan, task_status)
               if t.capability not in unserviceable]

    gap_updates = {}
    for task in plan.tasks:
        if task.capability in unserviceable and task.task_id not in task_status:
            gap_updates[task.task_id] = {
                "state": TaskState.SKIPPED.value,
                "capability": task.capability,
                "criticality": task.criticality.value,
                "error": f"no agent serves capability '{task.capability}'",
                "declared_gap": True,
            }

    for task_id in blocked_task_ids(plan, task_status):
        if task_id not in gap_updates:
            gap_updates[task_id] = {
                "state": TaskState.SKIPPED.value,
                "error": "upstream dependency failed",
                "declared_gap": True,
            }

    if gap_updates:
        log.info("run %s: %d task(s) skipped as declared gaps", state["run_id"], len(gap_updates))

    if not pending:
        return {"task_status": gap_updates, "status": "research_complete"}

    log.info(
        "run %s dispatching %d task(s) in parallel: %s",
        state["run_id"], len(pending), [t.capability for t in pending],
    )
    return {"task_status": gap_updates, "status": "researching"}


def dispatch_edge(state: dict):
    """
    Conditional edge returning `Send` objects -- the dynamic fan-out.

    Returning a list of `Send` makes LangGraph invoke `specialist_proxy` once
    per task, concurrently. The width is data-driven; the topology is not.
    """
    plan_data = state.get("plan")
    if not plan_data:
        return "collect"

    plan = ResearchPlan.model_validate(plan_data)
    task_status = state.get("task_status", {})

    pending = next_dispatch_layer(plan, task_status)
    skipped = {tid for tid, info in task_status.items() if info.get("declared_gap")}
    pending = [t for t in pending if t.task_id not in skipped]

    if not pending:
        return "collect"

    return [
        Send("specialist_proxy", {
            "run_id": state["run_id"],
            "task": t.model_dump(mode="json"),
            "trace_id": state.get("trace_id"),
        })
        for t in pending
    ]


async def specialist_proxy_node(payload: dict) -> dict:
    """
    Execute ONE task via A2A. Invoked N times concurrently by `Send`.

    This is the only node that talks to the data plane, and it is one node
    rather than nine: adding a specialist means registering an AgentCard, not
    editing the graph.

    Everything it returns targets a reduced state field, because N copies of
    this node write concurrently -- `evidence_ids` appends and `task_status`
    merges by task_id. Writing an un-reduced field from here would raise
    InvalidUpdateError under fan-out.
    """
    from contracts import TaskSpec

    run_id = payload["run_id"]
    task = TaskSpec.model_validate(payload["task"])
    client = get_a2a_client()

    result = await client.dispatch(
        capability=task.capability,
        inputs=task.inputs,
        run_id=run_id,
        task_id=task.task_id,
        traceparent=payload.get("trace_id"),
    )

    # Retry transport/provider failures up to the task's budget. Retries happen
    # here rather than via a graph loop so a flaky provider doesn't consume a
    # whole superstep per attempt.
    attempt = 1
    while result.state == TaskState.FAILED and attempt <= task.max_retries:
        attempt += 1
        log.info("retry %d/%d for %s", attempt, task.max_retries + 1, task.capability)
        result = await client.dispatch(
            capability=task.capability, inputs=task.inputs, run_id=run_id,
            task_id=task.task_id, attempt=attempt, traceparent=payload.get("trace_id"),
        )

    status_entry = {
        "state": result.state.value,
        "capability": task.capability,
        "criticality": task.criticality.value,
        "agent_id": result.agent_id,
        "confidence": result.confidence,
        "latency_ms": result.latency_ms,
        "attempts": attempt,
        "error": result.error,
        "degraded_reason": result.degraded_reason,
        "completed_at": datetime.now(timezone.utc).isoformat(),
    }

    if result.state == TaskState.FAILED:
        return {
            "task_status": {task.task_id: status_entry},
            "errors": [{
                "stage": "specialist",
                "task_id": task.task_id,
                "capability": task.capability,
                "criticality": task.criticality.value,
                "error": result.error,
            }],
        }

    # Persist to Postgres; state carries only the IDs.
    evidence_ids = await repository.save_evidence(result.evidence)
    claim_ids = await repository.save_claims(result.claims)

    return {
        "evidence_ids": evidence_ids,
        "claim_ids": claim_ids,
        "task_status": {task.task_id: status_entry},
    }


def route_after_collect(state: dict) -> str:
    """Loop back to the Director while tasks remain, then move on."""
    plan_data = state.get("plan")
    if not plan_data:
        return "done"

    plan = ResearchPlan.model_validate(plan_data)
    task_status = state.get("task_status", {})

    if next_dispatch_layer(plan, task_status):
        return "continue"
    return "done"


def collect_node(state: dict) -> dict:
    """
    Barrier after each parallel batch.

    Exists so the graph has a single join point where all `Send` branches
    converge before the Director decides on the next layer.
    """
    task_status = state.get("task_status", {})
    succeeded = sum(
        1 for info in task_status.values()
        if info.get("state") in (TaskState.SUCCEEDED.value, TaskState.DEGRADED.value)
    )
    failed = sum(1 for info in task_status.values() if info.get("state") == TaskState.FAILED.value)

    log.info(
        "run %s: %d task(s) done (%d ok, %d failed), %d evidence item(s)",
        state.get("run_id"), len(task_status), succeeded, failed,
        len(state.get("evidence_ids", [])),
    )
    return {}


def required_failures(plan: ResearchPlan, task_status: dict) -> list[str]:
    """REQUIRED tasks that did not produce usable evidence -- drives coverage scoring."""
    required = {t.task_id for t in plan.tasks if t.criticality == Criticality.REQUIRED}
    return [
        tid for tid in required
        if (task_status.get(tid, {}).get("state")
            not in (TaskState.SUCCEEDED.value, TaskState.DEGRADED.value))
    ]
