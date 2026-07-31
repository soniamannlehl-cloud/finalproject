"""
A2A message envelopes exchanged between the Research Director (control
plane) and specialist agents (data plane).

Kept deliberately small and transport-agnostic. The Director sends a
TaskRequest naming a capability; the specialist returns a TaskResult
carrying evidence and claims. Failures travel inside TaskResult rather
than as HTTP exceptions, so a dead upstream provider degrades the run
instead of crashing the workflow.
"""

from datetime import datetime

from pydantic import BaseModel, Field

from .enums import TaskState
from .evidence import Claim, Evidence


class A2ATaskRequest(BaseModel):
    """Control plane -> specialist."""

    task_id: str
    run_id: str
    capability: str
    inputs: dict = Field(default_factory=dict)
    timeout_s: int = 90
    attempt: int = Field(default=1, ge=1)

    # W3C traceparent, propagated so LangSmith/OTel stitches the specialist's
    # spans into the parent run tree instead of orphaning them in a separate
    # trace. Without this, cross-service observability silently breaks.
    traceparent: str | None = None


class A2ATaskResult(BaseModel):
    """
    Specialist -> control plane.

    A specialist that could not do its job returns state=FAILED with an
    `error` and empty evidence -- it does NOT raise. The Director decides
    whether that failure is retriable, degradable, or blocking.
    """

    task_id: str
    run_id: str
    agent_id: str
    capability: str
    state: TaskState

    evidence: list[Evidence] = Field(default_factory=list)
    claims: list[Claim] = Field(default_factory=list)

    confidence: float = Field(default=0.0, ge=0.0, le=1.0)
    error: str | None = None
    degraded_reason: str | None = Field(
        default=None, description="Set when a fallback provider or partial data was used"
    )
    providers_used: list[str] = Field(default_factory=list)

    started_at: datetime
    completed_at: datetime
    latency_ms: int = Field(ge=0)

    @property
    def succeeded(self) -> bool:
        return self.state in (TaskState.SUCCEEDED, TaskState.DEGRADED)
