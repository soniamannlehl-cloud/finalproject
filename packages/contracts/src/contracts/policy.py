"""
Recommendation gating policy -- deterministic, centralized, unit-testable.

The guardrail "never recommend Buy or Sell when evidence is insufficient"
is meaningless unless "insufficient" is defined numerically. This module is
that definition. It is pure logic with no LLM and no I/O, so its behavior
can be asserted exhaustively in tests and explained precisely to a reviewer.

Deliberately lives in `contracts` so the API service, the evaluation
harness, and the report renderer all apply identical thresholds.
"""

from pydantic import BaseModel

from .enums import RecommendationAction
from .safety import SafetyReport

# --- Thresholds ------------------------------------------------------------
# Tuned conservatively: this system's failure mode should be refusing to
# opine, never confidently opining on thin evidence.

MIN_EVIDENCE_SCORE_FOR_ANY_CALL = 0.60
"""Below this, no directional view is offered at all."""

MIN_CONFIDENCE_FOR_DIRECTIONAL = 0.70
"""Below this, BUY/SELL is downgraded to HOLD."""

MAX_TOLERATED_CONTRADICTIONS = 2
"""More unresolved contradictions than this suppresses a directional call."""


class GateResult(BaseModel):
    """Outcome of applying the policy, with a human-readable justification."""

    permitted_action: RecommendationAction
    was_downgraded: bool
    reasons: list[str]

    @property
    def is_directional(self) -> bool:
        return self.permitted_action in (
            RecommendationAction.BUY,
            RecommendationAction.SELL,
        )


def apply_recommendation_gate(
    proposed_action: RecommendationAction,
    confidence: float,
    safety: SafetyReport,
) -> GateResult:
    """
    Decide what the system is actually permitted to say.

    Takes the committee's proposed call and degrades it as required by
    evidence quality. The committee proposes; this policy disposes -- an
    LLM cannot talk its way past these thresholds.
    """
    reasons: list[str] = []

    # --- Hard blocks: refuse to opine at all -------------------------------
    if safety.unsupported_claim_ids:
        reasons.append(
            f"{len(safety.unsupported_claim_ids)} claim(s) cite evidence that does not "
            "resolve in the repository"
        )
        return GateResult(
            permitted_action=RecommendationAction.INSUFFICIENT_EVIDENCE,
            was_downgraded=proposed_action != RecommendationAction.INSUFFICIENT_EVIDENCE,
            reasons=reasons,
        )

    if safety.blocking_findings:
        reasons.extend(f"blocking: {f.message}" for f in safety.blocking_findings)
        return GateResult(
            permitted_action=RecommendationAction.INSUFFICIENT_EVIDENCE,
            was_downgraded=proposed_action != RecommendationAction.INSUFFICIENT_EVIDENCE,
            reasons=reasons,
        )

    if safety.evidence_score < MIN_EVIDENCE_SCORE_FOR_ANY_CALL:
        reasons.append(
            f"evidence score {safety.evidence_score:.2f} is below the "
            f"{MIN_EVIDENCE_SCORE_FOR_ANY_CALL:.2f} floor "
            f"(coverage {safety.coverage.coverage_ratio:.0%} of required research)"
        )
        return GateResult(
            permitted_action=RecommendationAction.INSUFFICIENT_EVIDENCE,
            was_downgraded=proposed_action != RecommendationAction.INSUFFICIENT_EVIDENCE,
            reasons=reasons,
        )

    # --- Soft blocks: opine, but only neutrally ----------------------------
    directional = proposed_action in (
        RecommendationAction.BUY,
        RecommendationAction.SELL,
    )

    if directional and confidence < MIN_CONFIDENCE_FOR_DIRECTIONAL:
        reasons.append(
            f"confidence {confidence:.2f} is below the "
            f"{MIN_CONFIDENCE_FOR_DIRECTIONAL:.2f} threshold for a directional call"
        )
        return GateResult(
            permitted_action=RecommendationAction.HOLD,
            was_downgraded=True,
            reasons=reasons,
        )

    if directional and safety.contradiction_count > MAX_TOLERATED_CONTRADICTIONS:
        reasons.append(
            f"{safety.contradiction_count} unresolved contradictions exceed the "
            f"tolerance of {MAX_TOLERATED_CONTRADICTIONS}"
        )
        return GateResult(
            permitted_action=RecommendationAction.HOLD,
            was_downgraded=True,
            reasons=reasons,
        )

    reasons.append("all evidence-quality thresholds satisfied")
    return GateResult(
        permitted_action=proposed_action,
        was_downgraded=False,
        reasons=reasons,
    )


def compute_evidence_score(
    coverage_ratio: float,
    stale_fraction: float = 0.0,
    degraded_fraction: float = 0.0,
) -> float:
    """
    Coverage discounted by data-quality problems.

    Staleness and provider degradation reduce the score but do not zero it:
    old or fallback-sourced data is worth less than fresh primary data, yet
    still worth more than nothing.
    """
    score = coverage_ratio * (1.0 - 0.30 * stale_fraction) * (1.0 - 0.15 * degraded_fraction)
    return max(0.0, min(1.0, score))
