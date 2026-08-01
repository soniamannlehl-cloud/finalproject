"""
Build the investment analyst thesis framework from measured evidence.

Stance and confidence are computed deterministically from signals; the
framework organizes findings into the standard 3-5 year ownership template.
"""

from __future__ import annotations

import logging
from typing import Any

from contracts import Polarity, RecommendationAction, StructuredThesis

from ..config import get_settings
from ..thesis.signals import Signal, compute_stance, extract_signals

log = logging.getLogger(__name__)

_VALUATION_LABELS = {
    "cheap": "Cheap — implied value above current price",
    "fair": "Fair — trading near peer-implied range",
    "expensive": "Expensive — implied value below current price",
    "insufficient_data": "Insufficient data — valuation range could not be computed",
}


def _valuation_opinion(evidence_by_cap: dict[str, list[dict]]) -> str:
    records = evidence_by_cap.get("valuation.estimate") or []
    if not records:
        return "insufficient_data"
    content = records[0].get("content") or {}
    vr = content.get("valuation_range")
    if not vr or vr.get("vs_current_pct") is None:
        return "insufficient_data"
    pct = vr["vs_current_pct"]
    if pct > 12:
        return "cheap"
    if pct < -12:
        return "expensive"
    return "fair"


def _missing_evidence(state: dict, safety_report: dict | None) -> list[str]:
    missing: list[str] = []
    if safety_report:
        coverage = safety_report.get("coverage") or {}
        for cap in coverage.get("failed_capabilities") or []:
            missing.append(cap.replace(".", " · ").replace("_", " "))
        for finding in safety_report.get("findings") or []:
            if finding.get("severity") == "blocking":
                msg = finding.get("message", "")
                if msg and msg not in missing:
                    missing.append(msg[:120])
    for _tid, info in (state.get("task_status") or {}).items():
        if info.get("state") == "degraded" and info.get("degraded_reason"):
            missing.append(f"{info.get('capability', 'task')}: {info['degraded_reason']}")
    return missing[:6]


def _catalysts(evidence_by_cap: dict[str, list[dict]]) -> tuple[list[str], list[str]]:
    positive: list[str] = []
    negative: list[str] = []

    for rec in evidence_by_cap.get("earnings.call") or []:
        content = rec.get("content") or {}
        beats = content.get("beats") or 0
        misses = content.get("misses") or 0
        if beats:
            positive.append(f"Earnings beat consensus in {beats} of recent quarters")
        if misses:
            negative.append(f"Earnings missed consensus in {misses} of recent quarters")
        if content.get("next_earnings_date"):
            positive.append(f"Upcoming earnings date: {content['next_earnings_date']}")

    for rec in evidence_by_cap.get("news.sentiment") or []:
        content = rec.get("content") or {}
        tone = content.get("tone") or ""
        count = content.get("article_count") or 0
        if tone == "bull" and count:
            positive.append(f"Recent news coverage ({count} articles) skews positive")
        elif tone == "bear" and count:
            negative.append(f"Recent news coverage ({count} articles) skews negative")
        elif tone == "neutral" and count:
            positive.append(f"News flow is neutral across {count} recent articles")

    for rec in evidence_by_cap.get("competitors.analysis") or []:
        content = rec.get("content") or {}
        comparison = content.get("comparison") or {}
        for metric, data in comparison.items():
            if not isinstance(data, dict):
                continue
            pct = data.get("percentile_rank")
            if pct is not None and pct >= 0.75:
                positive.append(f"Top-quartile vs peers on {metric.replace('_', ' ')}")
            elif pct is not None and pct <= 0.25:
                negative.append(f"Bottom-quartile vs peers on {metric.replace('_', ' ')}")

    return positive[:4], negative[:4]


def _recommendation_label(recommendation: dict | None) -> str:
    if not recommendation:
        return "pending"
    action = recommendation.get("action") or "pending"
    if isinstance(action, str):
        return action.lower().replace(" ", "_")
    return str(action)


def _primary_thesis_llm(
    company: str,
    stance: Polarity,
    bull: list[Signal],
    bear: list[Signal],
) -> str | None:
    settings = get_settings()
    if not settings.openai_api_key:
        return None
    # Skip LLM on early thesis revisions — evidence is still partial (layer 1–2).
    meaningful_signals = len(bull) + len(bear)
    if meaningful_signals < 2:
        return None
    try:
        from openai import OpenAI

        client = OpenAI(api_key=settings.openai_api_key)
        response = client.chat.completions.create(
            model=settings.resolve_model("thesis"),
            temperature=0.0,
            max_tokens=120,
            messages=[{
                "role": "user",
                "content": (
                    f"In one sentence, state the primary reason an investor would "
                    f"{'own' if stance == Polarity.BULL else 'avoid' if stance == Polarity.BEAR else 'hold'} "
                    f"{company} over 3-5 years. Use only these facts:\n"
                    f"Supporting: {'; '.join(s.detail for s in bull[:3]) or 'none'}\n"
                    f"Risks: {'; '.join(s.detail for s in bear[:2]) or 'none'}"
                ),
            }],
        )
        return (response.choices[0].message.content or "").strip() or None
    except Exception as e:  # noqa: BLE001
        log.warning("primary thesis LLM unavailable: %s", e)
        return None


def build_structured_thesis(
    *,
    company: str,
    ticker: str,
    evidence_records: list[dict],
    state: dict,
    recommendation: dict | None = None,
    safety_report: dict | None = None,
) -> StructuredThesis:
    """Assemble the analyst thesis framework from evidence and run state."""
    signals = extract_signals(evidence_records)
    stance, confidence = compute_stance(signals)
    bull = sorted([s for s in signals if s.polarity == Polarity.BULL], key=lambda s: -s.strength)
    bear = sorted([s for s in signals if s.polarity == Polarity.BEAR], key=lambda s: -s.strength)

    by_cap: dict[str, list[dict]] = {}
    for r in evidence_records:
        by_cap.setdefault(r["capability"], []).append(r)

    supporting = [s.detail for s in bull[:5]]
    if len(supporting) < 3:
        for rec in by_cap.get("investment.drivers") or []:
            content = rec.get("content") or {}
            for assessment in content.get("kpi_assessments") or []:
                if assessment.get("status") == "supportive":
                    detail = f"Driver KPI: {assessment.get('detail', assessment.get('kpi'))}"
                    if detail not in supporting:
                        supporting.append(detail)
                        if len(supporting) >= 5:
                            break
            if len(supporting) >= 3:
                break
    if len(supporting) < 3:
        for rec in by_cap.get("company.profile") or []:
            summary = rec.get("summary")
            if summary and summary not in supporting:
                supporting.append(summary)
                if len(supporting) >= 3:
                    break

    risks = [s.detail for s in bear[:5]]
    missing = _missing_evidence(state, safety_report)
    if not risks and missing:
        risks = missing[:3]

    pos_cat, neg_cat = _catalysts(by_cap)
    val_op = _valuation_opinion(by_cap)
    rec = _recommendation_label(recommendation)

    own_word = "own" if stance == Polarity.BULL else "avoid" if stance == Polarity.BEAR else "hold"
    core = f"Should investors {own_word} {company} ({ticker}) over the next 3-5 years?"

    primary = _primary_thesis_llm(company, stance, bull, bear)
    if not primary:
        if bull:
            primary = bull[0].detail
        elif stance == Polarity.BEAR and bear:
            primary = f"Key concern: {bear[0].detail}"
        else:
            primary = (
                "Insufficient verified evidence to identify a primary 3-5 year ownership thesis."
            )

    if rec == RecommendationAction.INSUFFICIENT_EVIDENCE.value:
        primary = (
            "Evidence coverage is too thin for a directional 3-5 year ownership call; "
            "additional research is required before forming a primary thesis."
        )

    return StructuredThesis(
        core_question=core,
        primary_thesis=primary,
        supporting_drivers=supporting or ["Pending — research still in progress"],
        key_risks=risks or ["No material risks identified from current evidence"],
        positive_catalysts=pos_cat or ["None identified from current data"],
        negative_catalysts=neg_cat or ["None identified from current data"],
        valuation_opinion=val_op,
        confidence=confidence,
        missing_evidence=missing or ["None — required research capabilities satisfied"],
        recommendation=rec,
    )


def framework_to_statement(framework: StructuredThesis) -> str:
    """Compact narrative for thesis version history."""
    return framework.primary_thesis
