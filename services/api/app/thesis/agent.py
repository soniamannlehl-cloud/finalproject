"""
Investment Thesis Agent.

Runs after every execution layer rather than once at the end, so the thesis
genuinely evolves as evidence arrives. Stance and confidence are computed
deterministically from signals (see signals.py); the structured framework
(see framework.py) organizes findings into the analyst template.
"""

import logging
from datetime import datetime, timezone

from contracts import Polarity, ThesisVersion

from ..evidence import repository as evidence_repo
from . import repository as thesis_repo
from .framework import build_structured_thesis, framework_to_statement
from .signals import compute_stance, extract_signals

log = logging.getLogger(__name__)


def _change_reason(
    prior: ThesisVersion | None, stance: Polarity, confidence: float, new_signal_count: int
) -> str:
    """
    Why this revision exists.

    The distinction between reversed / strengthened / weakened is what makes
    the version history readable as an argument rather than a changelog.
    """
    if prior is None:
        return f"Initial thesis formed from {new_signal_count} signal(s)."

    if prior.stance != stance:
        return (
            f"Stance revised from {prior.stance.value} to {stance.value} as new evidence "
            f"arrived ({new_signal_count} signal(s) now considered)."
        )

    delta = round(confidence - prior.confidence, 2)
    if delta >= 0.02:
        return (
            f"Thesis strengthened: confidence {prior.confidence} -> {confidence} "
            f"as corroborating evidence arrived ({new_signal_count} signal(s))."
        )
    if delta <= -0.02:
        return (
            f"Thesis weakened: confidence {prior.confidence} -> {confidence} "
            f"as conflicting evidence arrived ({new_signal_count} signal(s))."
        )
    return f"Thesis reaffirmed with {new_signal_count} signal(s); confidence steady at {confidence}."


async def thesis_node(state: dict) -> dict:
    """
    LangGraph node: form or update the thesis from evidence gathered so far.

    Invoked after each collect barrier. Failure here is non-fatal -- the run
    continues with the previous thesis rather than discarding completed
    research over a synthesis error.
    """
    run_id = state["run_id"]
    company = state.get("company_name") or state.get("ticker") or "the company"

    try:
        evidence_records = await evidence_repo.get_evidence_for_run(run_id)
        signals = extract_signals(evidence_records)
        stance, confidence = compute_stance(signals)

        prior = await thesis_repo.get_latest_version(run_id)
        version = (prior.version + 1) if prior else 1

        framework = build_structured_thesis(
            company=company,
            ticker=state.get("ticker") or "",
            evidence_records=evidence_records,
            state=state,
            recommendation=state.get("recommendation"),
            safety_report=state.get("safety_report"),
        )

        statement = framework_to_statement(framework)

        latest_capabilities = sorted({
            info.get("capability") for info in (state.get("task_status") or {}).values()
            if info.get("capability")
        })

        thesis = ThesisVersion(
            version=version,
            parent_version=prior.version if prior else None,
            run_id=run_id,
            statement=statement,
            framework=framework,
            stance=stance,
            confidence=confidence,
            supporting_claim_ids=[s.evidence_id for s in signals if s.polarity == Polarity.BULL],
            contradicting_claim_ids=[s.evidence_id for s in signals if s.polarity == Polarity.BEAR],
            change_reason=_change_reason(prior, stance, confidence, len(signals)),
            triggered_by=(
                f"research stage {version}: {', '.join(latest_capabilities[:5])}"
                if latest_capabilities else "initial research"
            ),
            created_at=datetime.now(timezone.utc),
        )

        await thesis_repo.save_thesis_version(thesis)
        log.info(
            "run %s thesis v%d: %s (confidence %.2f) from %d signal(s)",
            run_id, version, stance.value, confidence, len(signals),
        )

        return {
            "thesis_version": version,
            "thesis_stance": stance.value,
            "thesis_confidence": confidence,
            "thesis_framework": framework.model_dump(mode="json"),
        }

    except Exception as e:  # noqa: BLE001
        log.exception("thesis update failed for run %s", run_id)
        return {"errors": [{"stage": "thesis", "error": str(e)}]}
