"""
Earnings Agent.

Reports earnings history, surprise track record, and the next scheduled
date. Full call transcripts are not freely available, so this agent works
with the quantitative record instead and says so -- claiming transcript
analysis it did not perform would be a fabrication.

The surprise history is the substantive part: a company that has missed
consensus three quarters running is a materially different proposition from
one that has beaten it, and that pattern is computed here rather than
characterized by a model.
"""

import logging
from datetime import datetime, timezone

import yfinance as yf
from contracts import Capability, Evidence, SourceType
from tenacity import stop_after_attempt, wait_exponential

log = logging.getLogger(__name__)

AGENT_ID = "earnings_analyst_agent"


def _safe_float(value) -> float | None:
    try:
        f = float(value)
        return None if f != f else f  # NaN check
    except (TypeError, ValueError):
        return None


def _earnings_history(ticker_obj) -> list[dict]:
    """Recent reported vs. estimated EPS, newest first."""
    try:
        history = ticker_obj.earnings_history
    except Exception as e:  # noqa: BLE001
        log.info("earnings history unavailable: %s", e)
        return []

    if history is None or getattr(history, "empty", True):
        return []

    rows = []
    for index, row in history.iterrows():
        actual = _safe_float(row.get("epsActual"))
        estimate = _safe_float(row.get("epsEstimate"))
        rows.append({
            "period": str(index),
            "eps_actual": actual,
            "eps_estimate": estimate,
            "surprise": (
                round(actual - estimate, 4)
                if actual is not None and estimate is not None else None
            ),
            "surprise_pct": (
                round((actual - estimate) / abs(estimate) * 100, 2)
                if actual is not None and estimate not in (None, 0) else None
            ),
        })
    return rows[-8:][::-1]


def handle(inputs: dict, run_id: str, task_id: str) -> tuple[list[Evidence], float, str | None, list]:
    ticker = (inputs or {}).get("ticker")
    if not ticker:
        raise ValueError("earnings.call requires a 'ticker' input")

    try:
        t = yf.Ticker(ticker)
        info = t.info or {}
    except Exception as e:  # noqa: BLE001
        raise RuntimeError(f"earnings data unavailable for {ticker}: {e}") from e

    history = _earnings_history(t)

    # Track record, computed rather than characterized.
    scored = [h for h in history if h["surprise"] is not None]
    beats = sum(1 for h in scored if h["surprise"] > 0)
    misses = sum(1 for h in scored if h["surprise"] < 0)

    consecutive_misses = 0
    for h in scored:  # newest first
        if h["surprise"] < 0:
            consecutive_misses += 1
        else:
            break

    next_date = info.get("earningsTimestamp") or info.get("mostRecentQuarter")
    if isinstance(next_date, (int, float)):
        next_date = datetime.fromtimestamp(next_date, tz=timezone.utc).isoformat()

    content = {
        "ticker": ticker,
        "earnings_history": history,
        "quarters_analyzed": len(scored),
        "beats": beats,
        "misses": misses,
        "beat_rate": round(beats / len(scored), 2) if scored else None,
        "consecutive_misses": consecutive_misses,
        "next_earnings_date": next_date,
        "forward_eps": info.get("forwardEps"),
        "trailing_eps": info.get("trailingEps"),
        "earnings_growth": info.get("earningsGrowth"),
        "earnings_quarterly_growth": info.get("earningsQuarterlyGrowth"),
        # Stated explicitly so no downstream agent infers transcript coverage.
        "transcript_available": False,
        "transcript_note": (
            "Full earnings call transcripts are not available from the configured "
            "sources; this analysis covers the quantitative earnings record only."
        ),
    }

    if not scored:
        confidence, degraded = 0.35, "no earnings surprise history available"
    else:
        confidence = round(min(0.9, 0.5 + 0.05 * len(scored)), 2)
        degraded = "earnings call transcripts not available from configured sources"

    evidence = Evidence(
        evidence_id=Evidence.make_id(AGENT_ID, Capability.EARNINGS_CALL, content),
        run_id=run_id, task_id=task_id, agent_id=AGENT_ID,
        capability=Capability.EARNINGS_CALL,
        source_type=SourceType.ANALYST_ESTIMATE,
        source_name="Yahoo Finance earnings data",
        source_url=f"https://finance.yahoo.com/quote/{ticker}/analysis",
        citation=f"Earnings history and estimates for {ticker} ({len(scored)} quarter(s))",
        content=content,
        summary=(
            f"{beats} beat(s), {misses} miss(es) over {len(scored)} quarter(s)"
            if scored else "no earnings history"
        ),
        retrieved_at=datetime.now(timezone.utc),
        confidence=confidence,
        provider_degraded=True,  # transcripts always absent
    )

    return [evidence], confidence, degraded, []
