"""
Recommendation synthesizer node.

Applies the deterministic policy gate to the committee's proposal. The
committee argues; this node decides what the system is permitted to say.
"""

import logging
from datetime import datetime, timezone

from contracts import (
    CommitteePosition,
    CoverageReport,
    Recommendation,
    RecommendationAction,
    SafetyReport,
    apply_recommendation_gate,
)

log = logging.getLogger(__name__)


def _to_action(raw: str) -> RecommendationAction:
    try:
        return RecommendationAction(str(raw).lower().strip())
    except ValueError:
        return RecommendationAction.INSUFFICIENT_EVIDENCE


def _position(data: dict | None, default_role: str) -> CommitteePosition:
    data = data or {}
    return CommitteePosition(
        role=data.get("role", default_role),
        argument=data.get("argument") or "No argument produced.",
        conviction=float(data.get("conviction", 0.0)),
        claim_ids=data.get("claim_ids") or [],
    )


async def synthesizer_node(state: dict) -> dict:
    """Gate the committee proposal and produce the final Recommendation."""
    run_id = state["run_id"]
    proposal = state.get("committee_proposal") or {}

    safety_data = state.get("safety_report")
    if not safety_data:
        log.warning("run %s synthesizer invoked without safety report", run_id)
        safety = SafetyReport(
            run_id=run_id,
            coverage=CoverageReport(),
            evidence_score=0.0,
            created_at=datetime.now(timezone.utc),
        )
    else:
        safety = SafetyReport.model_validate(safety_data)

    proposed_action = _to_action(proposal.get("action", "insufficient_evidence"))
    confidence = float(proposal.get("confidence", 0.0))

    gate = apply_recommendation_gate(proposed_action, confidence, safety)

    recommendation = Recommendation(
        run_id=run_id,
        ticker=state.get("ticker") or "",
        action=gate.permitted_action,
        confidence=confidence,
        evidence_score=safety.evidence_score,
        time_horizon=proposal.get("time_horizon"),
        bull_case=_position(proposal.get("bull_case"), "bull_analyst"),
        bear_case=_position(proposal.get("bear_case"), "bear_analyst"),
        cio_rationale=proposal.get("cio_rationale") or "No rationale produced.",
        dissent=proposal.get("dissent"),
        conditions_that_would_change_this=proposal.get("conditions_that_would_change_this") or [],
        was_downgraded=gate.was_downgraded,
        gate_reasons=gate.reasons,
        created_at=datetime.now(timezone.utc),
    )

    log.info(
        "run %s recommendation: %s (proposed %s, downgraded=%s)",
        run_id, recommendation.action.value, proposed_action.value, gate.was_downgraded,
    )

    return {
        "recommendation": recommendation.model_dump(mode="json"),
        "status": "awaiting_committee_review",
    }
