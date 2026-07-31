"""
Investment Thesis Agent.

Runs after every execution layer rather than once at the end, so the thesis
genuinely evolves as evidence arrives: a three-layer plan produces three
revisions, each recording what changed and why. A thesis assembled in a
single pass at the end would satisfy the letter of "living thesis" and none
of its substance.

The stance is computed deterministically from measured signals first (see
signals.py); the LLM only writes prose around a conclusion already reached.
Without an API key the thesis still forms -- the statement is assembled from
the signals themselves.
"""

import logging
from datetime import datetime, timezone

from contracts import Polarity, ThesisVersion

from ..config import get_settings
from ..evidence import repository as evidence_repo
from . import repository as thesis_repo
from .signals import Signal, compute_stance, extract_signals

log = logging.getLogger(__name__)

_STANCE_WORDS = {
    Polarity.BULL: "constructive",
    Polarity.BEAR: "cautious",
    Polarity.NEUTRAL: "balanced",
}

_NARRATIVE_PROMPT = """You are a senior research analyst maintaining an evolving investment thesis.

Company: {company}
Stance derived from measured evidence: {stance} (confidence {confidence})

Supporting signals:
{bull}

Opposing signals:
{bear}

{prior}

Write the thesis in 3-4 sentences. Rules:
- The stance above was computed from the data; do NOT contradict or re-derive it.
- Reference only the signals listed. Introduce no new facts or figures.
- If prior thesis text is shown, write this as an UPDATE: say what changed and why.
- No buy/sell/hold advice."""


def _deterministic_statement(
    company: str, stance: Polarity, signals: list[Signal], version: int
) -> str:
    """
    Thesis text assembled from the signals themselves.

    Used when no LLM is configured. Deliberately plain -- it reads as a
    summary of findings rather than imitating analyst prose it cannot
    actually produce.
    """
    bull = [s for s in signals if s.polarity == Polarity.BULL]
    bear = [s for s in signals if s.polarity == Polarity.BEAR]

    if not signals:
        return (
            f"No directional signals have been derived for {company} yet; "
            "the thesis is pending further evidence."
        )

    parts = [f"Evidence gathered so far supports a {_STANCE_WORDS[stance]} view on {company}."]
    if bull:
        top = sorted(bull, key=lambda s: -s.strength)[:3]
        parts.append("Supporting: " + "; ".join(s.detail for s in top) + ".")
    if bear:
        top = sorted(bear, key=lambda s: -s.strength)[:3]
        parts.append("Offsetting: " + "; ".join(s.detail for s in top) + ".")
    if version > 1:
        parts.append(f"This is revision {version}, incorporating evidence from the latest research stage.")

    return " ".join(parts)


def _llm_statement(
    company: str, stance: Polarity, confidence: float,
    signals: list[Signal], prior: ThesisVersion | None,
) -> str | None:
    settings = get_settings()
    if not settings.openai_api_key:
        return None

    bull = [s for s in signals if s.polarity == Polarity.BULL]
    bear = [s for s in signals if s.polarity == Polarity.BEAR]

    prior_block = ""
    if prior:
        prior_block = (
            f"Prior thesis (v{prior.version}, stance {prior.stance.value}, "
            f"confidence {prior.confidence}):\n{prior.statement}"
        )

    try:
        from openai import OpenAI

        client = OpenAI(api_key=settings.openai_api_key)
        response = client.chat.completions.create(
            model=settings.resolve_model("thesis"),
            temperature=settings.temperature,
            max_tokens=400,
            messages=[{
                "role": "user",
                "content": _NARRATIVE_PROMPT.format(
                    company=company,
                    stance=_STANCE_WORDS[stance],
                    confidence=confidence,
                    bull="\n".join(f"- {s.detail}" for s in bull) or "- none",
                    bear="\n".join(f"- {s.detail}" for s in bear) or "- none",
                    prior=prior_block,
                ),
            }],
        )
        return (response.choices[0].message.content or "").strip() or None
    except Exception as e:  # noqa: BLE001
        log.warning("thesis narrative unavailable, using deterministic text: %s", e)
        return None


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

    # Threshold set just above float-rounding noise. A wider band previously
    # reported a real 0.92 -> 0.87 move as "stable", which understated a
    # genuine weakening the evidence had caused.
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

        statement = (
            _llm_statement(company, stance, confidence, signals, prior)
            or _deterministic_statement(company, stance, signals, version)
        )

        # Which research stage prompted this revision -- the audit trail for
        # "what caused the thesis to move".
        latest_capabilities = sorted({
            info.get("capability") for info in (state.get("task_status") or {}).values()
            if info.get("capability")
        })

        thesis = ThesisVersion(
            version=version,
            parent_version=prior.version if prior else None,
            run_id=run_id,
            statement=statement,
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
        }

    except Exception as e:  # noqa: BLE001
        log.exception("thesis update failed for run %s", run_id)
        return {"errors": [{"stage": "thesis", "error": str(e)}]}
