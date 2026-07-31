"""
Layer 1 -- deterministic safety checks.

These run before any LLM and cover everything that is mechanically
decidable. Freshness is timestamp arithmetic. Citation resolution is a set
operation against the repository. Coverage is division. Using a language
model for any of them would be slower, costlier, and *less* reliable --
an LLM asked "is this citation real?" can only guess, while a database
lookup knows.

This layer is the platform's floor. The semantic checks above it are
valuable but fallible; these are neither.
"""

import logging
import uuid
from datetime import datetime, timezone

from contracts import (
    FRESHNESS_POLICY,
    Criticality,
    CoverageReport,
    ResearchPlan,
    SafetyFinding,
    Severity,
    SourceType,
    TaskState,
)

log = logging.getLogger(__name__)


def make_finding(check: str, severity: Severity, message: str, **refs) -> SafetyFinding:
    """Construct a finding. Public because the pipeline emits findings too."""
    return SafetyFinding(
        finding_id=f"f_{uuid.uuid4().hex[:10]}",
        check_name=check,
        severity=severity,
        message=message,
        related_claim_ids=refs.get("claims", []),
        related_evidence_ids=refs.get("evidence", []),
        detected_at=datetime.now(timezone.utc),
    )


def check_freshness(evidence_records: list[dict]) -> tuple[list[SafetyFinding], list[str]]:
    """
    Flag evidence older than its source type tolerates.

    Filings and reported statements are immutable once published, so they
    never expire; market data goes stale in hours. Applying one blanket TTL
    would either discard valid filings or trust day-old quotes.
    """
    now = datetime.now(timezone.utc)
    findings: list[SafetyFinding] = []
    stale_ids: list[str] = []

    for record in evidence_records:
        try:
            source_type = SourceType(record["source_type"])
        except ValueError:
            continue

        limit = FRESHNESS_POLICY.get(source_type)
        if limit is None:
            continue  # immutable source

        retrieved = record["retrieved_at"]
        if retrieved.tzinfo is None:
            retrieved = retrieved.replace(tzinfo=timezone.utc)

        age = now - retrieved
        if age > limit:
            stale_ids.append(record["evidence_id"])
            findings.append(make_finding(
                "freshness", Severity.WARNING,
                f"{record['capability']} evidence is {age.days}d old, exceeding the "
                f"{limit.days}d tolerance for {source_type.value}",
                evidence=[record["evidence_id"]],
            ))

    return findings, stale_ids


def check_citations(
    claims: list[dict], known_evidence_ids: set[str]
) -> tuple[list[SafetyFinding], list[str]]:
    """
    Verify every claim cites evidence that actually exists.

    A claim referencing an ID absent from the repository is, by definition,
    fabricated -- the schema guarantees the list is non-empty, but not that
    its contents are real. This is the check that catches an LLM inventing a
    plausible-looking citation, and it hard-blocks a directional call.
    """
    findings: list[SafetyFinding] = []
    unsupported: list[str] = []

    for claim in claims:
        cited = set(claim.get("evidence_ids") or [])
        missing = cited - known_evidence_ids

        if not cited:
            # Should be unreachable via the Pydantic model; checked anyway
            # because a direct DB write could bypass it.
            unsupported.append(claim["claim_id"])
            findings.append(make_finding(
                "evidence_validation", Severity.BLOCKING,
                f"claim {claim['claim_id']} cites no evidence",
                claims=[claim["claim_id"]],
            ))
        elif missing:
            unsupported.append(claim["claim_id"])
            findings.append(make_finding(
                "evidence_validation", Severity.BLOCKING,
                f"claim {claim['claim_id']} cites {len(missing)} evidence ID(s) that do "
                f"not resolve in the repository: {sorted(missing)}",
                claims=[claim["claim_id"]], evidence=sorted(missing),
            ))

    return findings, unsupported


def check_coverage(
    plan: ResearchPlan, task_status: dict, evidence_by_capability: dict
) -> tuple[list[SafetyFinding], CoverageReport]:
    """
    Measure how much of the planned research produced usable evidence.

    Coverage is computed against REQUIRED capabilities only: an optional gap
    degrades the report, whereas a required gap undermines its foundation and
    should ultimately suppress a directional recommendation.
    """
    required = [t.capability for t in plan.tasks if t.criticality == Criticality.REQUIRED]

    satisfied, failed, degraded = [], [], []
    for task in plan.tasks:
        if task.criticality != Criticality.REQUIRED:
            continue

        state = (task_status.get(task.task_id) or {}).get("state")
        has_evidence = task.capability in evidence_by_capability

        if state == TaskState.SUCCEEDED.value and has_evidence:
            satisfied.append(task.capability)
        elif state == TaskState.DEGRADED.value and has_evidence:
            satisfied.append(task.capability)
            degraded.append(task.capability)
        else:
            failed.append(task.capability)

    findings: list[SafetyFinding] = []
    for capability in failed:
        findings.append(make_finding(
            "coverage", Severity.WARNING,
            f"required capability '{capability}' produced no usable evidence",
        ))

    report = CoverageReport(
        required_capabilities=required,
        satisfied_capabilities=satisfied,
        failed_capabilities=failed,
        degraded_capabilities=degraded,
    )

    if report.coverage_ratio < 0.5:
        findings.append(make_finding(
            "coverage", Severity.BLOCKING,
            f"only {report.coverage_ratio:.0%} of required research completed -- "
            "insufficient foundation for any directional view",
        ))

    return findings, report


def check_confidence_consistency(
    evidence_records: list[dict], thesis_confidence: float | None
) -> list[SafetyFinding]:
    """
    Flag a thesis more confident than the evidence beneath it.

    Guards a specific failure mode: high-confidence conclusions resting on
    low-confidence or degraded inputs. Confidence should not increase as it
    propagates upward.
    """
    if thesis_confidence is None or not evidence_records:
        return []

    confidences = [r["confidence"] for r in evidence_records if r.get("confidence") is not None]
    if not confidences:
        return []

    mean_evidence_confidence = sum(confidences) / len(confidences)

    if thesis_confidence > mean_evidence_confidence + 0.25:
        return [make_finding(
            "confidence_consistency", Severity.WARNING,
            f"thesis confidence {thesis_confidence:.2f} materially exceeds mean evidence "
            f"confidence {mean_evidence_confidence:.2f}",
        )]
    return []
