"""
Build the evidence brief the investment committee deliberates over.

The committee receives a condensed digest, not raw filings or full metric
dumps. This module extracts structured summaries from persisted evidence so
the control plane never passes megabytes of content across the A2A boundary.
"""

import logging

from ..config import get_settings

log = logging.getLogger(__name__)

# Map common reviewer feedback phrases to capabilities for replanning.
_FEEDBACK_CAPABILITY_HINTS: dict[str, list[str]] = {
    "valuation": ["valuation.estimate"],
    "competitor": ["competitors.analysis"],
    "competition": ["competitors.analysis"],
    "peer": ["competitors.analysis"],
    "risk": ["risk.analysis"],
    "financial": ["financials.statements", "financials.ratios"],
    "sec": ["filings.sec"],
    "filing": ["filings.sec"],
    "earnings": ["earnings.call"],
    "news": ["news.sentiment"],
    "sentiment": ["news.sentiment"],
}


def parse_replan_capabilities(feedback: str | None) -> list[str]:
    """Infer which specialist capabilities to re-run from human feedback."""
    if not feedback:
        return []

    lower = feedback.lower()
    requested: list[str] = []
    for keyword, capabilities in _FEEDBACK_CAPABILITY_HINTS.items():
        if keyword in lower:
            requested.extend(capabilities)
    return sorted(set(requested))


async def build_brief_payload(state: dict) -> dict:
    """
    Assemble a serializable brief dict from workflow state and Postgres.

    Returns a dict compatible with the committee service's EvidenceBrief model.
    """
    from ..evidence import repository as evidence_repo

    run_id = state["run_id"]
    evidence_records = await evidence_repo.get_evidence_for_run(run_id)
    claims = await evidence_repo.get_claims_for_run(run_id)

    settings = get_settings()
    max_claims = settings.max_brief_claims if hasattr(settings, "max_brief_claims") else 40

    key_metrics: dict[str, str] = {}
    valuation: dict | None = None
    peer_positioning: dict = {}
    detected_risks: list[dict] = []
    sentiment: dict | None = None
    earnings_record: dict | None = None
    filings: dict | None = None

    for record in evidence_records:
        content = record.get("content") or {}
        capability = record.get("capability", "")

        if capability == "financials.ratios":
            for name, detail in (content.get("metrics") or {}).items():
                if isinstance(detail, dict):
                    key_metrics[name] = detail.get("formatted") or str(detail.get("value", ""))
                else:
                    key_metrics[name] = str(detail)

        elif capability == "valuation.estimate":
            vr = content.get("valuation_range") or {}
            valuation = {
                "methods": [
                    r.get("label") or r.get("method")
                    for r in (content.get("results") or [])
                    if r.get("applicable")
                ],
                "range": (
                    f"{vr.get('low')}-{vr.get('high')} vs current {vr.get('current_price')}"
                    if vr.get("low") is not None else None
                ),
            }

        elif capability == "competitors.analysis":
            for metric, detail in (content.get("comparison") or content.get("peer_comparison") or {}).items():
                if isinstance(detail, dict):
                    peer_positioning[metric] = (
                        f"percentile {detail.get('percentile_rank')} "
                        f"(subject {detail.get('subject')}, peer median {detail.get('peer_median')})"
                    )
                else:
                    peer_positioning[metric] = str(detail)

        elif capability == "risk.analysis":
            for risk in content.get("detected_risks") or content.get("risks") or []:
                if isinstance(risk, dict):
                    detected_risks.append(risk)

        elif capability == "news.sentiment":
            sentiment = {
                "tone": content.get("overall_tone") or content.get("tone"),
                "article_count": content.get("article_count", 0),
                "low_coverage": content.get("low_coverage", False),
            }

        elif capability == "earnings.call":
            earnings_record = {
                "beats": content.get("beats", 0),
                "misses": content.get("misses", 0),
                "consecutive_misses": content.get("consecutive_misses", 0),
            }

        elif capability == "filings.sec":
            filings = {
                "filing_count": content.get("filing_count", 0),
                "has_annual_report": content.get("has_annual_report", False),
            }

    safety_report = state.get("safety_report") or {}
    coverage = safety_report.get("coverage") or {}
    required_caps = coverage.get("required_capabilities") or []
    satisfied_caps = coverage.get("satisfied_capabilities") or []
    coverage_ratio = (
        len(satisfied_caps) / len(required_caps) if required_caps else 0.0
    )

    declared_gaps = [
        tid for tid, info in (state.get("task_status") or {}).items()
        if info.get("declared_gap")
    ]

    unverified_checks = [
        f.get("message", "")
        for f in safety_report.get("findings", [])
        if str(f.get("check_name", "")).endswith("_not_run")
    ]

    brief_claims = [
        {
            "claim_id": c["claim_id"],
            "text": c["text"],
            "category": c.get("category", "general"),
            "polarity": c.get("polarity", "neutral"),
            "confidence": float(c.get("confidence", 0.0)),
            "evidence_ids": c.get("evidence_ids") or [],
        }
        for c in claims[:max_claims]
    ]

    framework = state.get("thesis_framework") or {}
    thesis_statement = framework.get("primary_thesis") if isinstance(framework, dict) else None

    return {
        "run_id": run_id,
        "ticker": state.get("ticker") or "",
        "company_name": state.get("company_name") or state.get("ticker") or "",
        "industry": state.get("industry"),
        "classification": state.get("classification"),
        "thesis_statement": thesis_statement,
        "thesis_stance": state.get("thesis_stance"),
        "thesis_confidence": state.get("thesis_confidence"),
        "key_metrics": key_metrics,
        "valuation": valuation,
        "peer_positioning": peer_positioning,
        "detected_risks": detected_risks,
        "sentiment": sentiment,
        "earnings_record": earnings_record,
        "filings": filings,
        "claims": brief_claims,
        "evidence_score": state.get("evidence_score") or 0.0,
        "coverage_ratio": coverage_ratio,
        "declared_gaps": declared_gaps,
        "unverified_checks": unverified_checks,
    }
