"""
Deterministic signal extraction from evidence.

The thesis stance is computed here, from measured values, before any LLM is
involved. That ordering is the point: a language model asked to "form a view
on this company" will produce a confident narrative regardless of what the
evidence supports. A model asked to *explain* a stance that was already
derived from leverage ratios and peer percentiles cannot invent a bull case
out of bear data.

Each signal carries the number that produced it, so every element of the
thesis traces back to a specific evidence record.
"""

import logging
from dataclasses import dataclass

from contracts import Polarity

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class Signal:
    """One directional indicator derived from a measured value."""

    name: str
    polarity: Polarity
    strength: float          # 0..1 -- how much weight this carries
    detail: str              # human-readable, includes the number
    evidence_id: str
    capability: str

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "polarity": self.polarity.value,
            "strength": self.strength,
            "detail": self.detail,
            "evidence_id": self.evidence_id,
            "capability": self.capability,
        }


def _ordinal(n: int) -> str:
    """1st, 2nd, 3rd, 83rd, 100th -- this text reaches the final report."""
    if 11 <= (n % 100) <= 13:
        return f"{n}th"
    return f"{n}{ {1: 'st', 2: 'nd', 3: 'rd'}.get(n % 10, 'th') }".replace(" ", "")


def _metric(content: dict, name: str) -> dict | None:
    """Pull a computed metric, or None when it wasn't meaningful."""
    metric = (content.get("metrics") or {}).get(name)
    if metric and metric.get("meaningful"):
        return metric
    return None


def _from_financial_ratios(ev: dict) -> list[Signal]:
    content, eid = ev["content"], ev["evidence_id"]
    signals: list[Signal] = []

    if m := _metric(content, "revenue_growth"):
        v = m["value"]
        if v > 0.20:
            signals.append(Signal("strong_revenue_growth", Polarity.BULL, min(1.0, v),
                                  f"revenue growth {m['formatted']}", eid, ev["capability"]))
        elif v < -0.05:
            signals.append(Signal("revenue_decline", Polarity.BEAR, min(1.0, abs(v) * 2),
                                  f"revenue declined {m['formatted']}", eid, ev["capability"]))

    if m := _metric(content, "operating_margin"):
        v = m["value"]
        if v > 0.20:
            signals.append(Signal("strong_operating_margin", Polarity.BULL, 0.7,
                                  f"operating margin {m['formatted']}", eid, ev["capability"]))
        elif v < 0:
            signals.append(Signal("operating_losses", Polarity.BEAR, 0.9,
                                  f"operating margin {m['formatted']}", eid, ev["capability"]))

    if m := _metric(content, "free_cash_flow"):
        if m["value"] > 0:
            signals.append(Signal("positive_free_cash_flow", Polarity.BULL, 0.6,
                                  f"free cash flow {m['formatted']}", eid, ev["capability"]))
        else:
            signals.append(Signal("cash_burn", Polarity.BEAR, 0.85,
                                  f"free cash flow {m['formatted']}", eid, ev["capability"]))

    if m := _metric(content, "debt_to_ebitda"):
        v = m["value"]
        if v > 4.0:
            signals.append(Signal("high_leverage", Polarity.BEAR, min(1.0, v / 8),
                                  f"debt/EBITDA {m['formatted']}", eid, ev["capability"]))
        elif v < 1.5:
            signals.append(Signal("low_leverage", Polarity.BULL, 0.5,
                                  f"debt/EBITDA {m['formatted']}", eid, ev["capability"]))

    return signals


def _from_valuation(ev: dict) -> list[Signal]:
    """
    Valuation cuts both ways, which is why it is a signal rather than a verdict:
    trading below peer-implied value is bullish only if the discount is not
    deserved -- something this system deliberately does not claim to know.
    """
    content, eid = ev["content"], ev["evidence_id"]
    vr = content.get("valuation_range")
    if not vr or vr.get("vs_current_pct") is None:
        return []

    gap = vr["vs_current_pct"]
    if gap > 15:
        return [Signal("trades_below_peer_implied_value", Polarity.BULL, min(1.0, gap / 50),
                       f"peer-implied midpoint {gap:+.1f}% vs current price",
                       eid, ev["capability"])]
    if gap < -15:
        return [Signal("trades_above_peer_implied_value", Polarity.BEAR, min(1.0, abs(gap) / 50),
                       f"peer-implied midpoint {gap:+.1f}% vs current price",
                       eid, ev["capability"])]
    return []


def _from_competitors(ev: dict) -> list[Signal]:
    content, eid = ev["content"], ev["evidence_id"]
    comparison = content.get("comparison") or {}
    signals: list[Signal] = []

    # Percentile rank against real peers -- the only way a margin figure
    # becomes interpretable.
    for metric, label in (
        ("gross_margin", "gross margin"),
        ("operating_margin", "operating margin"),
        ("return_on_equity", "return on equity"),
        ("revenue_growth", "revenue growth"),
    ):
        c = comparison.get(metric) or {}
        rank = c.get("percentile_rank")
        if rank is None:
            continue
        # Stated as a percentile rather than "top N%": at rank 1.0 the latter
        # renders as "top 0% of peers", which reads as nonsense.
        percentile = int(round(rank * 100))
        if rank >= 0.75:
            signals.append(Signal(f"peer_leading_{metric}", Polarity.BULL, rank,
                                  f"{label} at the {_ordinal(percentile)} percentile among peers",
                                  eid, ev["capability"]))
        elif rank <= 0.25:
            signals.append(Signal(f"peer_lagging_{metric}", Polarity.BEAR, 1 - rank,
                                  f"{label} at the {_ordinal(percentile)} percentile among peers",
                                  eid, ev["capability"]))
    return signals


def _from_risk(ev: dict) -> list[Signal]:
    content, eid = ev["content"], ev["evidence_id"]
    return [
        Signal(f"risk_{r['id']}", Polarity.BEAR,
               0.9 if r["severity"] == "high" else 0.6,
               f"{r['title']}: {r['detail']}", eid, ev["capability"])
        for r in content.get("detected_risks", [])
    ]


def _from_sentiment(ev: dict) -> list[Signal]:
    content, eid = ev["content"], ev["evidence_id"]

    # Thin coverage is not neutral sentiment -- it is absence of information,
    # and treating it as a signal would manufacture conviction from silence.
    if content.get("low_coverage") or content.get("article_count", 0) == 0:
        return []

    tone = content.get("tone")
    if tone == Polarity.BULL.value:
        return [Signal("positive_media_sentiment", Polarity.BULL, 0.4,
                       f"positive tone across {content['article_count']} articles",
                       eid, ev["capability"])]
    if tone == Polarity.BEAR.value:
        return [Signal("negative_media_sentiment", Polarity.BEAR, 0.5,
                       f"negative tone across {content['article_count']} articles",
                       eid, ev["capability"])]
    return []


def _from_earnings(ev: dict) -> list[Signal]:
    content, eid = ev["content"], ev["evidence_id"]
    signals: list[Signal] = []

    if content.get("consecutive_misses", 0) >= 2:
        signals.append(Signal("consecutive_earnings_misses", Polarity.BEAR, 0.7,
                              f"{content['consecutive_misses']} consecutive earnings misses",
                              eid, ev["capability"]))
    elif (rate := content.get("beat_rate")) is not None and rate >= 0.75:
        signals.append(Signal("consistent_earnings_beats", Polarity.BULL, 0.5,
                              f"beat consensus in {int(rate*100)}% of recent quarters",
                              eid, ev["capability"]))
    return signals


def _from_investment_drivers(ev: dict) -> list[Signal]:
    content, eid = ev["content"], ev["evidence_id"]
    signals: list[Signal] = []
    for assessment in content.get("kpi_assessments") or []:
        status = assessment.get("status")
        if status == "supportive":
            signals.append(Signal(
                f"kpi_{assessment.get('kpi', 'unknown')}", Polarity.BULL, 0.55,
                f"KPI supportive: {assessment.get('detail', assessment.get('kpi'))}",
                eid, ev["capability"],
            ))
        elif status == "challenged":
            signals.append(Signal(
                f"kpi_{assessment.get('kpi', 'unknown')}", Polarity.BEAR, 0.55,
                f"KPI challenged: {assessment.get('detail', assessment.get('kpi'))}",
                eid, ev["capability"],
            ))
    return signals


_EXTRACTORS = {
    "financials.ratios": _from_financial_ratios,
    "valuation.estimate": _from_valuation,
    "competitors.analysis": _from_competitors,
    "risk.analysis": _from_risk,
    "news.sentiment": _from_sentiment,
    "earnings.call": _from_earnings,
    "investment.drivers": _from_investment_drivers,
}


def extract_signals(evidence_records: list[dict]) -> list[Signal]:
    """Derive every directional signal the current evidence supports."""
    signals: list[Signal] = []
    for ev in evidence_records:
        extractor = _EXTRACTORS.get(ev.get("capability"))
        if extractor is None:
            continue
        try:
            signals.extend(extractor(ev))
        except Exception as e:  # noqa: BLE001
            # One malformed evidence record must not abort thesis formation.
            log.warning("signal extraction failed for %s: %s", ev.get("capability"), e)
    return signals


def compute_stance(signals: list[Signal]) -> tuple[Polarity, float]:
    """
    Weighted stance and confidence.

    Confidence rises with corroboration and falls when signals conflict: five
    indicators pointing the same way is a stronger position than five split
    three-to-two, even though both have five data points. Encoding that
    prevents the system from sounding equally certain in both cases.
    """
    if not signals:
        return Polarity.NEUTRAL, 0.0

    bull = sum(s.strength for s in signals if s.polarity == Polarity.BULL)
    bear = sum(s.strength for s in signals if s.polarity == Polarity.BEAR)
    total = bull + bear
    if total == 0:
        return Polarity.NEUTRAL, 0.2

    net = (bull - bear) / total          # -1..1
    agreement = abs(net)                  # 1.0 when unanimous, 0.0 when evenly split
    breadth = min(1.0, len(signals) / 8)  # more independent signals -> firmer view

    confidence = round(min(0.95, 0.25 + 0.45 * agreement + 0.30 * breadth), 2)

    if net > 0.25:
        return Polarity.BULL, confidence
    if net < -0.25:
        return Polarity.BEAR, confidence
    # Genuinely mixed evidence is reported as neutral with reduced confidence
    # rather than being forced into a direction.
    return Polarity.NEUTRAL, round(confidence * 0.8, 2)
