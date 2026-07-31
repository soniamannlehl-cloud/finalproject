"""
Valuation Agent.

Applies the valuation methods the Planner selected for this company's
industry, against peer medians. Every figure is computed in Python with
stated inputs.

Two properties this agent is careful about:

  * A method the industry does not support returns "not applicable" with a
    reason, rather than a number. Producing a P/E for a REIT is worse than
    producing nothing, because it looks authoritative.
  * Implied values are stated as a RANGE across methods, not a single price
    target. A point estimate implies a precision this evidence cannot carry,
    and the spread between methods is itself informative.
"""

import logging
from datetime import datetime, timezone

from contracts import Capability, Evidence, SourceType

from ..tools.peers_tool import get_industry_peers, get_peer_metrics, median
from ..tools.yfinance_tool import get_financials

log = logging.getLogger(__name__)

AGENT_ID = "valuation_analyst_agent"

# Which company metric pairs with which peer multiple, and what it scales.
_METHOD_SPEC: dict[str, dict] = {
    "pe_multiple": {"peer_key": "trailing_pe", "driver": "net_income", "label": "P/E"},
    "price_book": {"peer_key": "price_to_book", "driver": "total_equity", "label": "P/B"},
    "ev_revenue": {"peer_key": "ev_to_revenue", "driver": "revenue", "label": "EV/Revenue"},
    "ev_ebitda": {"peer_key": "ev_to_ebitda", "driver": "ebitda", "label": "EV/EBITDA"},
}

# Methods requiring data this platform does not yet source. Declared
# explicitly so an unsupported method is an honest gap, not a silent omission.
_UNSUPPORTED = {
    "dcf": "discounted cash flow requires forward projections not available from current sources",
    "ffo_multiple": "FFO is not reported in standard statement data; REIT supplemental filings needed",
    "nav": "net asset value requires property-level or holdings data not currently sourced",
    "sum_of_parts": "segment-level financials are not currently sourced",
    "rule_of_40": "computed as a metric by the financial analyst rather than a valuation method",
}


def _apply_multiple(method: str, financials: dict, peer_median: float | None) -> dict:
    """Implied equity value from a peer multiple applied to the company's driver."""
    spec = _METHOD_SPEC[method]
    driver_value = financials.get(spec["driver"])

    if peer_median is None:
        return {"method": method, "label": spec["label"], "applicable": False,
                "reason": "no peer median available for this multiple"}
    if driver_value is None:
        return {"method": method, "label": spec["label"], "applicable": False,
                "reason": f"company {spec['driver']} not reported"}
    if driver_value <= 0:
        return {"method": method, "label": spec["label"], "applicable": False,
                "reason": f"{spec['driver']} is negative or zero -- multiple is not meaningful"}

    implied = peer_median * driver_value

    # EV-based multiples value the whole enterprise; equity holders own what
    # remains after net debt. Skipping this bridge overstates equity value for
    # any leveraged company.
    if method.startswith("ev_"):
        debt = financials.get("total_debt") or 0
        implied = implied - debt

    shares = financials.get("shares_outstanding")
    return {
        "method": method,
        "label": spec["label"],
        "applicable": True,
        "peer_median_multiple": round(peer_median, 2),
        "driver": spec["driver"],
        "driver_value": driver_value,
        "implied_equity_value": round(implied, 2),
        "implied_price_per_share": round(implied / shares, 2) if shares and implied > 0 else None,
        "net_debt_adjusted": method.startswith("ev_"),
    }


def handle(inputs: dict, run_id: str, task_id: str) -> tuple[list[Evidence], float, str | None, list]:
    ticker = (inputs or {}).get("ticker")
    if not ticker:
        raise ValueError("valuation.estimate requires a 'ticker' input")

    requested = (inputs or {}).get("valuation_methods") or ["pe_multiple", "ev_ebitda"]
    industry = (inputs or {}).get("industry")

    financials = get_financials(ticker)

    if not industry:
        try:
            import yfinance as yf

            industry = (yf.Ticker(ticker).info or {}).get("industry")
        except Exception:  # noqa: BLE001
            industry = None

    peers = get_industry_peers(industry or "", exclude_ticker=ticker)
    peer_metrics = get_peer_metrics([p["ticker"] for p in peers]) if peers else {}

    results, unsupported = [], []
    for method in requested:
        if method in _UNSUPPORTED:
            unsupported.append({"method": method, "reason": _UNSUPPORTED[method]})
            continue
        if method not in _METHOD_SPEC:
            unsupported.append({"method": method, "reason": "method not implemented"})
            continue

        peer_median = median([m.get(_METHOD_SPEC[method]["peer_key"]) for m in peer_metrics.values()])
        results.append(_apply_multiple(method, financials, peer_median))

    applicable = [r for r in results if r["applicable"] and r.get("implied_price_per_share")]
    prices = [r["implied_price_per_share"] for r in applicable]
    current_price = financials.get("price")

    valuation_range = None
    if prices:
        low, high = min(prices), max(prices)
        valuation_range = {
            "low": low,
            "high": high,
            "midpoint": round((low + high) / 2, 2),
            "current_price": current_price,
            "methods_used": len(prices),
            # Stated as a range, and only versus the midpoint, because the
            # spread across methods is a genuine uncertainty signal.
            "vs_current_pct": (
                round((((low + high) / 2) - current_price) / current_price * 100, 1)
                if current_price else None
            ),
        }

    content = {
        "ticker": ticker,
        "industry": industry,
        "requested_methods": requested,
        "results": results,
        "unsupported_methods": unsupported,
        "valuation_range": valuation_range,
        "peer_count": len(peer_metrics),
        "current_price": current_price,
    }

    if not applicable:
        confidence, degraded = 0.2, "no valuation method could be applied with available data"
    else:
        confidence = round(min(0.85, 0.35 + 0.15 * len(applicable) + 0.02 * len(peer_metrics)), 2)
        degraded = (
            f"{len(unsupported)} requested method(s) unsupported by available data"
            if unsupported else None
        )

    evidence = Evidence(
        evidence_id=Evidence.make_id(AGENT_ID, Capability.VALUATION, content),
        run_id=run_id, task_id=task_id, agent_id=AGENT_ID,
        capability=Capability.VALUATION,
        source_type=SourceType.COMPUTED,
        source_name="Peer-relative multiple valuation",
        citation=(
            f"Valuation of {ticker} using {len(applicable)} method(s) against "
            f"{len(peer_metrics)} industry peer(s)"
        ),
        content=content,
        summary=(
            f"implied {valuation_range['low']}-{valuation_range['high']} vs current {current_price}"
            if valuation_range else "no applicable valuation method"
        ),
        retrieved_at=datetime.now(timezone.utc),
        confidence=confidence,
        provider_degraded=degraded is not None,
    )

    return [evidence], confidence, degraded, []
