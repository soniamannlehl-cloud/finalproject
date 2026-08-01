"""
Competitor Analysis Agent.

Positions the company against its actual industry peers. A multiple only
means something relative to a comparison set: 30x earnings is unremarkable
in one industry and demanding in another, and only the peer median makes
that judgment possible.

Positioning is computed deterministically (percentile rank against the peer
set). The LLM is not involved -- "trades above the peer median on P/E" is
arithmetic, not interpretation.
"""

import logging
from datetime import datetime, timezone

from contracts import Capability, Evidence, SourceType

from ..tools.peers_tool import get_industry_peers, get_peer_metrics, median

log = logging.getLogger(__name__)

AGENT_ID = "competitor_analyst_agent"

_COMPARED_METRICS = (
    "trailing_pe", "price_to_book", "ev_to_revenue", "ev_to_ebitda",
    "gross_margin", "operating_margin", "revenue_growth", "return_on_equity",
)

_FACTOR_TO_METRIC: dict[str, str] = {
    "revenue_growth": "revenue_growth",
    "gross_margin": "gross_margin",
    "operating_margin": "operating_margin",
    "ev_to_revenue": "ev_to_revenue",
    "ev_to_ebitda": "ev_to_ebitda",
    "price_to_book": "price_to_book",
    "return_on_equity": "return_on_equity",
    "rd_to_revenue": "rd_to_revenue",
    "efficiency_ratio": "efficiency_ratio",
    "dividend_yield": "dividend_yield",
    "payout_ratio": "payout_ratio",
    "ffo_multiple": "ev_to_ebitda",
    "occupancy_rate": "operating_margin",
}


def _metrics_from_profile(competitive_factors: list[str] | None) -> tuple[str, ...]:
    """Derive peer comparison metrics from industry profile competitive factors."""
    if not competitive_factors:
        return _COMPARED_METRICS
    selected: list[str] = []
    for factor in competitive_factors:
        for key, metric in _FACTOR_TO_METRIC.items():
            if key in factor.lower() and metric not in selected:
                selected.append(metric)
    return tuple(selected) if selected else _COMPARED_METRICS


def _percentile_rank(value: float | None, peer_values: list[float | None]) -> float | None:
    """Fraction of peers this value exceeds. None when uncomparable."""
    if value is None:
        return None
    clean = [v for v in peer_values if v is not None and v == v]
    if not clean:
        return None
    return round(sum(1 for v in clean if value > v) / len(clean), 2)


def handle(inputs: dict, run_id: str, task_id: str) -> tuple[list[Evidence], float, str | None, list]:
    ticker = (inputs or {}).get("ticker")
    industry = (inputs or {}).get("industry")
    sector = (inputs or {}).get("sector")
    if not ticker:
        raise ValueError("competitors.analysis requires a 'ticker' input")

    profile = (inputs or {}).get("industry_profile") or {}
    competitive_factors = (inputs or {}).get("competitive_factors") or profile.get("competitive_factors")
    compared_metrics = _metrics_from_profile(competitive_factors)

    if not industry or not sector:
        try:
            import yfinance as yf

            info = yf.Ticker(ticker).info or {}
            industry = industry or info.get("industry")
            sector = sector or info.get("sector")
        except Exception:  # noqa: BLE001
            pass

    peers = get_industry_peers(industry or "", exclude_ticker=ticker, sector=sector)

    if not peers:
        content = {
            "ticker": ticker, "industry": industry, "peers": [],
            "peer_count": 0, "comparison": {},
            "note": "no industry peer set could be resolved",
        }
        evidence = Evidence(
            evidence_id=Evidence.make_id(AGENT_ID, Capability.COMPETITOR_ANALYSIS, content, run_id),
            run_id=run_id, task_id=task_id, agent_id=AGENT_ID,
            capability=Capability.COMPETITOR_ANALYSIS,
            source_type=SourceType.MARKET_DATA, source_name="Yahoo Finance industry data",
            citation=f"Industry peer lookup for {ticker} ({industry or 'industry unknown'})",
            content=content, summary="no peers resolved",
            retrieved_at=datetime.now(timezone.utc), confidence=0.2,
            provider_degraded=True,
        )
        return [evidence], 0.2, "no industry peer set available for comparison", []

    all_metrics = get_peer_metrics([ticker] + [p["ticker"] for p in peers])
    subject = all_metrics.get(ticker, {})
    peer_metrics = {t: m for t, m in all_metrics.items() if t != ticker}

    comparison = {}
    for metric in compared_metrics:
        peer_values = [m.get(metric) for m in peer_metrics.values()]
        peer_median = median(peer_values)
        subject_value = subject.get(metric)

        comparison[metric] = {
            "subject": subject_value,
            "peer_median": peer_median,
            "percentile_rank": _percentile_rank(subject_value, peer_values),
            "vs_median": (
                round(subject_value - peer_median, 4)
                if subject_value is not None and peer_median is not None else None
            ),
            "peers_with_data": sum(1 for v in peer_values if v is not None),
        }

    comparable = sum(1 for c in comparison.values() if c["peer_median"] is not None)
    confidence = round(min(0.9, 0.4 + 0.06 * len(peer_metrics) + 0.03 * comparable), 2)
    degraded = None if comparable >= 4 else "thin peer metric coverage for comparison"

    content = {
        "ticker": ticker,
        "profile_id": profile.get("profile_id") or (inputs or {}).get("profile_id"),
        "competitive_factors": competitive_factors,
        "industry": industry,
        "peers": peers,
        "peer_count": len(peer_metrics),
        "peer_metrics": peer_metrics,
        "subject_metrics": subject,
        "comparison": comparison,
        "comparable_metric_count": comparable,
    }

    evidence = Evidence(
        evidence_id=Evidence.make_id(AGENT_ID, Capability.COMPETITOR_ANALYSIS, content, run_id),
        run_id=run_id, task_id=task_id, agent_id=AGENT_ID,
        capability=Capability.COMPETITOR_ANALYSIS,
        source_type=SourceType.MARKET_DATA,
        source_name="Yahoo Finance industry constituents",
        citation=(
            f"Peer comparison for {ticker} against {len(peer_metrics)} "
            f"{industry or 'industry'} constituent(s)"
        ),
        content=content,
        summary=f"compared against {len(peer_metrics)} peers on {comparable} metrics",
        retrieved_at=datetime.now(timezone.utc),
        confidence=confidence,
        provider_degraded=degraded is not None,
    )

    return [evidence], confidence, degraded, []
