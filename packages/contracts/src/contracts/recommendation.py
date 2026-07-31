"""
The investment committee's output.

Produced by the CrewAI committee (Bull / Bear / CIO), then passed through
the deterministic gate in `policy.py` before it can reach a report. The
committee proposes; the policy disposes.
"""

from datetime import datetime

from pydantic import BaseModel, Field

from .enums import RecommendationAction


class CommitteePosition(BaseModel):
    """One committee member's argued position."""

    role: str = Field(description="'bull_analyst' | 'bear_analyst' | 'cio'")
    argument: str
    key_points: list[str] = Field(default_factory=list)
    claim_ids: list[str] = Field(
        default_factory=list, description="Claims this position rests on"
    )
    conviction: float = Field(ge=0.0, le=1.0)


class Recommendation(BaseModel):
    """
    The final, gated investment view.

    `gate_reasons` and `was_downgraded` are retained so the report can state
    plainly when the system declined to make a stronger call and why -- the
    refusal is itself a reportable finding, not a silent omission.
    """

    run_id: str
    ticker: str

    action: RecommendationAction
    confidence: float = Field(ge=0.0, le=1.0)
    evidence_score: float = Field(ge=0.0, le=1.0)

    target_price: float | None = None
    time_horizon: str | None = Field(default=None, description="e.g. '12 months'")

    bull_case: CommitteePosition
    bear_case: CommitteePosition
    cio_rationale: str

    dissent: str | None = Field(
        default=None, description="Recorded when Bull and Bear did not converge"
    )
    conditions_that_would_change_this: list[str] = Field(
        default_factory=list,
        description="Observable triggers that would invalidate this view",
    )

    was_downgraded: bool = Field(
        default=False, description="True if the safety gate weakened the committee's call"
    )
    gate_reasons: list[str] = Field(default_factory=list)

    created_at: datetime
