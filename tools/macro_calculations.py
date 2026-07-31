"""
tools/macro_calculations.py

Deterministic trend and performance calculations for the Macro & Industry
Analyst Agent. Like tools/financial_calculations.py, the LLM never computes
these numbers itself -- it only interprets what these functions return.

Used for:
  1. Universal macro indicators (GDP growth, CPI, fed funds rate, unemployment)
     pulled from FRED historical series -- compute_trend() turns a series of
     readings into a rising/falling/stable direction.
  2. Sector ETF performance (current + 3mo/6mo/YTD trend + vs S&P 500) pulled
     from yfinance historical prices -- compute_sector_performance().
"""

from typing import Optional


def compute_trend(values: list, stable_threshold: float = 0.02) -> dict:
    """
    `values`: chronological list of numeric readings (oldest first) spanning
    the lookback window (brief specifies 6-12mo for macro indicators).
    `stable_threshold`: fractional change below which direction is "stable"
    rather than "rising"/"falling" (default 2%).

    Returns {"direction": "rising"|"falling"|"stable"|"unknown",
             "change_pct": float | None,
             "start_value": float | None, "end_value": float | None}
    """
    values = [v for v in values if v is not None]
    if len(values) < 2:
        return {"direction": "unknown", "change_pct": None, "start_value": None, "end_value": None}

    start, end = values[0], values[-1]
    if start == 0:
        return {"direction": "unknown", "change_pct": None, "start_value": start, "end_value": end}

    change_pct = (end - start) / abs(start)
    if change_pct > stable_threshold:
        direction = "rising"
    elif change_pct < -stable_threshold:
        direction = "falling"
    else:
        direction = "stable"

    return {"direction": direction, "change_pct": change_pct, "start_value": start, "end_value": end}


def compute_period_return(start_price: Optional[float], end_price: Optional[float]) -> Optional[float]:
    """Simple return over a price series window: (end - start) / start."""
    if start_price is None or end_price is None or start_price == 0:
        return None
    return (end_price - start_price) / start_price


def compute_sector_performance(sector_prices: dict, benchmark_prices: dict,
                                windows: Optional[list] = None) -> dict:
    """
    `sector_prices` / `benchmark_prices`: dicts with keys "current" and, for
    each window in `windows`, "{window}_start" (e.g. "3mo_start"). Benchmark
    is expected to be S&P 500 (SPY) prices over the same windows.

    Returns {"current": float | None,
             "trend": {window: pct_return | None, ...},
             "vs_sp500": {window: relative_pct | None, ...}}
    """
    windows = windows or ["3mo", "6mo", "ytd"]
    trend = {}
    vs_sp500 = {}

    sector_current = sector_prices.get("current")
    benchmark_current = benchmark_prices.get("current")

    for window in windows:
        sector_return = compute_period_return(sector_prices.get(f"{window}_start"), sector_current)
        benchmark_return = compute_period_return(benchmark_prices.get(f"{window}_start"), benchmark_current)
        trend[window] = sector_return
        if sector_return is not None and benchmark_return is not None:
            vs_sp500[window] = sector_return - benchmark_return
        else:
            vs_sp500[window] = None

    return {"current": sector_current, "trend": trend, "vs_sp500": vs_sp500}


def compute_indicator_summary(values: list, current_value: Optional[float] = None,
                               stable_threshold: float = 0.02) -> dict:
    """
    Convenience wrapper for a single macro indicator (e.g. CPI, fed funds
    rate): combines the latest reading with its trend direction into the
    {current, trend} shape used in InvestmentResearchState's macro_indicators.
    """
    trend = compute_trend(values, stable_threshold=stable_threshold)
    current = current_value if current_value is not None else (values[-1] if values else None)
    return {"current": current, "trend": trend["direction"], "change_pct": trend["change_pct"]}
