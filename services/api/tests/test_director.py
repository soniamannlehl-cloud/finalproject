"""
Research Director scheduling tests.

The Director decides what runs, when, and what to do when something fails.
Two behaviors matter most and are easy to get subtly wrong:

  * A task whose dependency FAILED must be skipped, not run against missing
    inputs. Analysis built on absent data is worse than a declared gap.
  * A failed dependency must not stall the run forever waiting for a
    predecessor that will never succeed.
"""

import pytest
from contracts import (
    Criticality, IndustryPlaybook, ResearchPlan, TaskSpec, TaskState, ValuationMethod,
)
from datetime import datetime, timezone

from app.director.director import (
    blocked_task_ids, next_dispatch_layer, required_failures, route_after_collect,
)

NOW = datetime.now(timezone.utc)


def task(task_id, capability="cap", depends_on=None, required=True):
    return TaskSpec(
        task_id=task_id, capability=capability, depends_on=depends_on or [],
        criticality=Criticality.REQUIRED if required else Criticality.OPTIONAL,
        rationale="test",
    )


def plan_with(tasks):
    return ResearchPlan(
        plan_id="p1", run_id="r1", ticker="NVDA", company_name="NVIDIA",
        classification=IndustryPlaybook.TECHNOLOGY, industry="Semiconductors",
        sector="Technology", valuation_methods=[ValuationMethod.EV_REVENUE],
        required_metrics=["revenue_growth"], tasks=tasks,
        fallback_strategy="degrade", planner_rationale="test", created_at=NOW,
    )


def status(**kwargs):
    """Build a task_status dict: status(t1='succeeded', t2='failed')."""
    return {tid: {"state": state} for tid, state in kwargs.items()}


class TestDispatchLayering:
    def test_independent_tasks_dispatch_together(self):
        p = plan_with([task("t1"), task("t2"), task("t3")])
        assert len(next_dispatch_layer(p, {})) == 3

    def test_dependent_task_waits(self):
        p = plan_with([task("t1"), task("t2", depends_on=["t1"])])
        first = next_dispatch_layer(p, {})
        assert [t.task_id for t in first] == ["t1"]

    def test_dependent_task_runs_after_success(self):
        p = plan_with([task("t1"), task("t2", depends_on=["t1"])])
        ready = next_dispatch_layer(p, status(t1=TaskState.SUCCEEDED.value))
        assert [t.task_id for t in ready] == ["t2"]

    def test_degraded_counts_as_complete(self):
        """Partial data is still data -- a degraded upstream shouldn't block."""
        p = plan_with([task("t1"), task("t2", depends_on=["t1"])])
        ready = next_dispatch_layer(p, status(t1=TaskState.DEGRADED.value))
        assert [t.task_id for t in ready] == ["t2"]

    def test_failed_dependency_does_not_release_dependent(self):
        """The correctness case: never analyze against inputs that failed to arrive."""
        p = plan_with([task("t1"), task("t2", depends_on=["t1"])])
        assert next_dispatch_layer(p, status(t1=TaskState.FAILED.value)) == []

    def test_already_dispatched_tasks_are_not_redispatched(self):
        p = plan_with([task("t1"), task("t2")])
        ready = next_dispatch_layer(p, status(t1=TaskState.SUCCEEDED.value))
        assert [t.task_id for t in ready] == ["t2"]


class TestBlockedTasks:
    def test_dependent_of_failed_task_is_blocked(self):
        p = plan_with([task("t1"), task("t2", depends_on=["t1"])])
        assert blocked_task_ids(p, status(t1=TaskState.FAILED.value)) == ["t2"]

    def test_pending_dependency_is_not_yet_blocked(self):
        """Still waiting is different from can-never-run."""
        p = plan_with([task("t1"), task("t2", depends_on=["t1"])])
        assert blocked_task_ids(p, {}) == []

    def test_succeeded_dependency_blocks_nothing(self):
        p = plan_with([task("t1"), task("t2", depends_on=["t1"])])
        assert blocked_task_ids(p, status(t1=TaskState.SUCCEEDED.value)) == []


class TestRouting:
    def test_continues_while_work_remains(self):
        p = plan_with([task("t1"), task("t2")])
        state = {"plan": p.model_dump(mode="json"), "task_status": status(t1="succeeded")}
        assert route_after_collect(state) == "continue"

    def test_done_when_all_tasks_finished(self):
        p = plan_with([task("t1"), task("t2")])
        state = {
            "plan": p.model_dump(mode="json"),
            "task_status": status(t1="succeeded", t2="succeeded"),
        }
        assert route_after_collect(state) == "done"

    def test_done_when_remaining_tasks_are_permanently_blocked(self):
        """A failed dependency must terminate the loop, not spin it."""
        p = plan_with([task("t1"), task("t2", depends_on=["t1"])])
        state = {"plan": p.model_dump(mode="json"), "task_status": status(t1="failed")}
        assert route_after_collect(state) == "done"

    def test_missing_plan_terminates(self):
        assert route_after_collect({}) == "done"


class TestRequiredFailures:
    def test_optional_failures_are_not_counted(self):
        """Optional gaps degrade the report; they don't undermine its foundation."""
        p = plan_with([task("t1", required=True), task("t2", required=False)])
        st = status(t1=TaskState.SUCCEEDED.value, t2=TaskState.FAILED.value)
        assert required_failures(p, st) == []

    def test_required_failure_is_counted(self):
        p = plan_with([task("t1", required=True)])
        assert required_failures(p, status(t1=TaskState.FAILED.value)) == ["t1"]

    def test_never_dispatched_required_task_counts_as_failure(self):
        """A REQUIRED task that never ran is a coverage hole, not a neutral event."""
        p = plan_with([task("t1", required=True)])
        assert required_failures(p, {}) == ["t1"]
