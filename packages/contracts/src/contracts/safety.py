"""
Safety and validation findings.

Findings are produced by a layered pipeline (see services/api/app/safety):
deterministic checks run first because they are free, fast, and cannot
flake; LLM judgment is reserved for contradiction and hallucination
detection, where semantic reasoning is genuinely required.
"""

from datetime import datetime

from pydantic import BaseModel, Field

from .enums import Severity


class SafetyFinding(BaseModel):
    """One issue detected by one check."""

    finding_id: str
    check_name: str = Field(description="e.g. 'freshness', 'hallucination'")
    severity: Severity
    message: str
    related_claim_ids: list[str] = Field(default_factory=list)
    related_evidence_ids: list[str] = Field(default_factory=list)
    detected_at: datetime


class CoverageReport(BaseModel):
    """
    How much of the plan actually produced usable evidence.

    This drives `evidence_score`, which in turn gates whether a directional
    recommendation is permitted at all.
    """

    required_capabilities: list[str] = Field(default_factory=list)
    satisfied_capabilities: list[str] = Field(default_factory=list)
    failed_capabilities: list[str] = Field(default_factory=list)
    degraded_capabilities: list[str] = Field(default_factory=list)

    @property
    def coverage_ratio(self) -> float:
        """Fraction of REQUIRED capabilities that returned usable evidence."""
        if not self.required_capabilities:
            return 0.0
        return len(self.satisfied_capabilities) / len(self.required_capabilities)


class SafetyReport(BaseModel):
    """Aggregate safety verdict for a run, consumed by the gating policy."""

    run_id: str
    findings: list[SafetyFinding] = Field(default_factory=list)
    coverage: CoverageReport

    evidence_score: float = Field(
        ge=0.0, le=1.0, description="Coverage discounted by staleness and degradation"
    )
    stale_evidence_ids: list[str] = Field(default_factory=list)
    unsupported_claim_ids: list[str] = Field(
        default_factory=list, description="Claims citing evidence that does not resolve"
    )
    contradiction_count: int = 0
    created_at: datetime

    @property
    def blocking_findings(self) -> list[SafetyFinding]:
        return [f for f in self.findings if f.severity == Severity.BLOCKING]

    @property
    def is_blocking(self) -> bool:
        """True if a directional recommendation must be suppressed."""
        return bool(self.blocking_findings) or bool(self.unsupported_claim_ids)
