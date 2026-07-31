"""
The living investment thesis.

The thesis is versioned rather than overwritten. Every revision records
what changed and why, so the claim "the thesis evolves as evidence
arrives" is demonstrable -- you can show v1 -> v5 with the trigger and
rationale for each step, instead of a single string that silently mutates.
"""

from datetime import datetime

from pydantic import BaseModel, Field

from .enums import Polarity


class ThesisVersion(BaseModel):
    """One immutable snapshot of the investment thesis."""

    version: int = Field(ge=1)
    parent_version: int | None = Field(
        default=None, description="None only for v1; forms the revision chain"
    )
    run_id: str

    statement: str = Field(description="The thesis in plain language")
    stance: Polarity = Field(description="Current directional lean of the evidence")
    confidence: float = Field(ge=0.0, le=1.0)

    supporting_claim_ids: list[str] = Field(default_factory=list)
    contradicting_claim_ids: list[str] = Field(default_factory=list)

    change_reason: str = Field(
        description="Why the thesis moved -- 'initial', 'strengthened by X', 'revised after Y'"
    )
    triggered_by: str = Field(
        description="task_id, safety finding, or HITL feedback that caused this revision"
    )
    created_at: datetime

    @property
    def evidence_balance(self) -> int:
        """Net support: positive means corroborated, negative means contested."""
        return len(self.supporting_claim_ids) - len(self.contradicting_claim_ids)


class ThesisHistory(BaseModel):
    """The full revision chain for a run, newest last."""

    run_id: str
    versions: list[ThesisVersion] = Field(default_factory=list)

    @property
    def current(self) -> ThesisVersion | None:
        return self.versions[-1] if self.versions else None

    def confidence_trajectory(self) -> list[tuple[int, float]]:
        """(version, confidence) pairs -- rendered as a sparkline in the report."""
        return [(v.version, v.confidence) for v in self.versions]
