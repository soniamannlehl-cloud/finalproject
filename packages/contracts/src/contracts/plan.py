"""
The research plan -- the artifact that makes planning explicit and inspectable.

The Planner Agent emits a ResearchPlan; the Research Director executes it.
Because the plan is data rather than control flow, it can be logged, diffed
across revisions, rendered in the UI, and asserted against in tests -- which
is what distinguishes "explicit planning" from a hardcoded pipeline.
"""

from datetime import datetime

from pydantic import BaseModel, Field, model_validator

from .enums import Criticality, IndustryPlaybook, ValuationMethod


class TaskSpec(BaseModel):
    """
    One unit of research work.

    Note `capability` rather than `agent_id`: the Planner declares WHAT it
    needs, and the Director resolves WHO provides it via A2A discovery at
    dispatch time. This indirection is what lets the specialist fleet change
    without touching planning logic.
    """

    task_id: str
    capability: str = Field(description="A2A capability, e.g. 'financials.ratios'")
    inputs: dict = Field(default_factory=dict)
    depends_on: list[str] = Field(
        default_factory=list, description="task_ids that must succeed first"
    )
    criticality: Criticality = Criticality.REQUIRED
    timeout_s: int = Field(default=90, gt=0)
    max_retries: int = Field(default=2, ge=0)
    rationale: str = Field(
        description="Why the Planner included this task -- surfaced in traces and UI"
    )


class ResearchPlan(BaseModel):
    """
    A complete, versioned research strategy for one company.

    Revisions are created when HITL #2 requests additional analysis. Keeping
    `parent_revision` and `replan_reason` makes the planning history legible:
    you can show exactly how human feedback changed the strategy.
    """

    plan_id: str
    run_id: str
    revision: int = Field(default=0, ge=0)
    parent_revision: int | None = None
    replan_reason: str | None = Field(
        default=None, description="Human feedback or safety finding that forced a replan"
    )

    ticker: str
    company_name: str
    classification: IndustryPlaybook
    industry: str
    sector: str

    valuation_methods: list[ValuationMethod] = Field(min_length=1)
    required_metrics: list[str] = Field(
        min_length=1, description="Industry-appropriate metrics, e.g. ['nim','roe'] for banks"
    )
    peer_tickers: list[str] = Field(default_factory=list)

    tasks: list[TaskSpec] = Field(min_length=1)
    fallback_strategy: str = Field(
        description="What to do if REQUIRED tasks fail -- stated up front, not improvised"
    )
    planner_rationale: str = Field(
        description="Why this strategy suits this company; the planning chain-of-thought artifact"
    )

    created_at: datetime

    @model_validator(mode="after")
    def _validate_dag(self) -> "ResearchPlan":
        """
        Reject malformed plans at construction time.

        An LLM produces this object, so it can hallucinate a dependency on a
        task that doesn't exist or emit a cycle. Catching that here turns a
        confusing mid-execution hang into a clear validation error the
        Planner node can retry against.
        """
        ids = [t.task_id for t in self.tasks]
        if len(set(ids)) != len(ids):
            raise ValueError("duplicate task_id in plan")

        known = set(ids)
        for task in self.tasks:
            unknown = set(task.depends_on) - known
            if unknown:
                raise ValueError(f"task {task.task_id} depends on unknown task(s): {unknown}")
            if task.task_id in task.depends_on:
                raise ValueError(f"task {task.task_id} depends on itself")

        # Cycle detection via Kahn's algorithm; execution_layers() relies on
        # the graph being acyclic.
        remaining = {t.task_id: set(t.depends_on) for t in self.tasks}
        while remaining:
            ready = [tid for tid, deps in remaining.items() if not deps]
            if not ready:
                raise ValueError(f"dependency cycle among tasks: {sorted(remaining)}")
            for tid in ready:
                del remaining[tid]
            for deps in remaining.values():
                deps.difference_update(ready)

        return self

    def execution_layers(self) -> list[list[TaskSpec]]:
        """
        Group tasks into layers that can each run fully in parallel.

        Layer 0 has no dependencies; layer N depends only on layers < N. The
        Director dispatches one layer at a time via LangGraph's Send API, so
        parallelism is derived from the plan's data rather than hardcoded in
        the graph topology.
        """
        by_id = {t.task_id: t for t in self.tasks}
        remaining = {t.task_id: set(t.depends_on) for t in self.tasks}
        layers: list[list[TaskSpec]] = []

        while remaining:
            ready = sorted(tid for tid, deps in remaining.items() if not deps)
            layers.append([by_id[tid] for tid in ready])
            for tid in ready:
                del remaining[tid]
            for deps in remaining.values():
                deps.difference_update(ready)

        return layers

    def required_capabilities(self) -> set[str]:
        """Capabilities whose failure should reduce the evidence score."""
        return {t.capability for t in self.tasks if t.criticality == Criticality.REQUIRED}
