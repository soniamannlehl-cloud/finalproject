"""
The safety pipeline -- layers L0 through L3.

Ordering is deliberate: cheapest and most reliable first.

  L0  SCHEMA         enforced in contracts; a Claim cannot exist uncited
  L1  DETERMINISTIC  freshness, citation resolution, coverage   free, exact
  L2  SEMANTIC       hallucination, contradiction               costly, fallible
  L3  POLICY         numeric gating in contracts/policy.py      deterministic

L1 runs unconditionally. L2 runs when it can, and declares itself skipped
when it cannot -- never silently passing. L3 then converts the accumulated
findings into what the system is actually permitted to say.

The evidence score is penalised when L2 could not run, so an unverified run
cannot present itself with the same authority as a verified one.
"""

import logging
from datetime import datetime, timezone

from contracts import (
    CoverageReport,
    ResearchPlan,
    SafetyReport,
    Severity,
    compute_evidence_score,
)

from ..evidence import repository as evidence_repo
from . import deterministic, semantic

log = logging.getLogger(__name__)

# How much unverified semantic safety costs the evidence score. Enough to
# matter -- an unverified run should not clear the 0.60 directional floor on
# coverage alone -- without zeroing genuinely-gathered evidence.
UNVERIFIED_SEMANTIC_PENALTY = 0.15


async def run_safety_pipeline(state: dict) -> SafetyReport:
    """Execute all layers and produce the aggregate verdict."""
    run_id = state["run_id"]

    evidence_records = await evidence_repo.get_evidence_for_run(run_id)
    claims = await evidence_repo.get_claims_for_run(run_id)
    evidence_by_id = {r["evidence_id"]: r for r in evidence_records}
    evidence_by_capability = await evidence_repo.evidence_summary(run_id)

    findings = []

    # --- L1: deterministic ------------------------------------------------
    freshness_findings, stale_ids = deterministic.check_freshness(evidence_records)
    findings.extend(freshness_findings)

    citation_findings, unsupported_from_citations = deterministic.check_citations(
        claims, set(evidence_by_id)
    )
    findings.extend(citation_findings)

    plan = ResearchPlan.model_validate(state["plan"]) if state.get("plan") else None
    if plan:
        coverage_findings, coverage = deterministic.check_coverage(
            plan, state.get("task_status", {}), evidence_by_capability
        )
        findings.extend(coverage_findings)
    else:
        coverage = CoverageReport()

    findings.extend(
        deterministic.check_confidence_consistency(
            evidence_records, state.get("thesis_confidence")
        )
    )

    # --- L2: semantic ------------------------------------------------------
    filed_facts = next(
        (r["content"].get("filed_facts") for r in evidence_records
         if r["capability"] == "filings.sec" and r.get("content")),
        None,
    )
    semantic_result = semantic.run_semantic_checks(claims, evidence_by_id, filed_facts)
    findings.extend(semantic_result.findings)

    # --- scoring -----------------------------------------------------------
    stale_fraction = len(stale_ids) / len(evidence_records) if evidence_records else 0.0
    degraded_count = sum(1 for r in evidence_records if r.get("provider_degraded"))
    degraded_fraction = degraded_count / len(evidence_records) if evidence_records else 0.0

    evidence_score = compute_evidence_score(
        coverage_ratio=coverage.coverage_ratio,
        stale_fraction=stale_fraction,
        degraded_fraction=degraded_fraction,
    )

    # An unverified run is not an equally trustworthy run.
    if not semantic_result.was_verified:
        evidence_score = max(0.0, evidence_score - UNVERIFIED_SEMANTIC_PENALTY)
        # Surfaced as findings so an unverified run says so on its face,
        # rather than only in a score the reader has to interpret.
        for skipped in semantic_result.checks_skipped:
            findings.append(
                deterministic.make_finding(
                    check=f"{skipped['check']}_not_run",
                    severity=Severity.WARNING,
                    message=f"{skipped['check']} check did not run: {skipped['reason']}",
                )
            )

    unsupported = sorted(set(unsupported_from_citations) | set(semantic_result.unsupported_claim_ids))

    report = SafetyReport(
        run_id=run_id,
        findings=findings,
        coverage=coverage,
        evidence_score=round(evidence_score, 3),
        stale_evidence_ids=stale_ids,
        unsupported_claim_ids=unsupported,
        contradiction_count=semantic_result.contradiction_count,
        created_at=datetime.now(timezone.utc),
    )

    log.info(
        "run %s safety: score=%.2f coverage=%.0f%% findings=%d unsupported=%d "
        "contradictions=%d semantic_verified=%s",
        run_id, report.evidence_score, coverage.coverage_ratio * 100,
        len(findings), len(unsupported), report.contradiction_count,
        semantic_result.was_verified,
    )

    return report


async def safety_node(state: dict) -> dict:
    """
    LangGraph node: run the safety pipeline.

    A pipeline failure must NOT be treated as a pass. If the checks
    themselves error, the run is marked unsafe with a zero evidence score --
    failing closed, because the alternative is shipping unverified analysis
    that looks verified.
    """
    try:
        report = await run_safety_pipeline(state)
    except Exception as e:  # noqa: BLE001
        log.exception("safety pipeline failed for run %s", state.get("run_id"))
        return {
            "safety_report": None,
            "evidence_score": 0.0,
            "status": "safety_failed",
            "errors": [{"stage": "safety", "error": str(e)}],
        }

    return {
        "safety_report": report.model_dump(mode="json"),
        "evidence_score": report.evidence_score,
        "status": "safety_blocked" if report.is_blocking else "safety_passed",
    }
