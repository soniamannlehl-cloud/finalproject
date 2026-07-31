"""
agents/macro_industry_analyst.py

Macro & Industry Analyst Agent -- three deterministic/quantitative layers
(universal macro indicators via FRED, sector ETF performance via yfinance,
industry-specific indicators via data/sector_indicators.json) plus one
qualitative layer (industry landscape via news search). Waits on Industry
Identification for `industry`/`sector`.
"""

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional

import yfinance as yf
from fredapi import Fred

from config import get_llm, FRED_API_KEY, MACRO_TREND_LOOKBACK_MONTHS, SENTIMENT_LOOKBACK_DAYS
from tools.macro_calculations import compute_indicator_summary, compute_sector_performance
from tools.news_search import search_news

PERSONA = (
    "You are an expert macroeconomic and industry analyst who evaluates "
    "economic conditions, sector performance, and competitive dynamics."
)

SECTOR_INDICATORS_PATH = Path(__file__).resolve().parent.parent / "data" / "sector_indicators.json"

# Universal macro indicators -- every company gets these. `units="pc1"` asks
# FRED for year-over-year percent change (so CPI reads as an inflation RATE,
# not the ever-rising raw price index, which would always show "rising").
FRED_SERIES = {
    "gdp_growth": {"series_id": "A191RL1Q225SBEA", "units": None},
    "inflation_cpi": {"series_id": "CPIAUCSL", "units": "pc1"},
    "fed_funds_rate": {"series_id": "FEDFUNDS", "units": None},
    "unemployment_rate": {"series_id": "UNRATE", "units": None},
}


def _load_sector_indicators_table() -> dict:
    with open(SECTOR_INDICATORS_PATH, encoding="utf-8") as f:
        return json.load(f)


def _lookup_sector_etf(sector: Optional[str]) -> Optional[str]:
    table = _load_sector_indicators_table()
    return table["sector_etfs"].get(sector)


def _lookup_industry_indicator_specs(industry: Optional[str], sector: Optional[str]) -> list:
    table = _load_sector_indicators_table()
    return (
        table["industry_indicators"].get(industry)
        or table["sector_default_indicators"].get(sector)
        or table["unknown_default"]
    )


# ---------------------------------------------------------------------------
# Layer 1: universal macro indicators (FRED)
# ---------------------------------------------------------------------------

def _fetch_fred_series_values(fred: Fred, series_id: str, months_back: int, units: Optional[str] = None) -> list:
    kwargs = {"units": units} if units else {}
    start = datetime.utcnow() - timedelta(days=months_back * 31)
    series = fred.get_series(series_id, observation_start=start, **kwargs)
    return [float(v) for v in series.dropna().tolist()]


def _fetch_macro_indicators() -> Optional[dict]:
    if not FRED_API_KEY:
        return None
    try:
        fred = Fred(api_key=FRED_API_KEY)
    except Exception:
        return None

    indicators = {}
    for name, spec in FRED_SERIES.items():
        try:
            values = _fetch_fred_series_values(fred, spec["series_id"], MACRO_TREND_LOOKBACK_MONTHS, spec["units"])
        except Exception:
            continue
        if values:
            indicators[name] = compute_indicator_summary(values, current_value=values[-1])

    return indicators or None


def _fetch_industry_specific_indicators(industry: Optional[str], sector: Optional[str]) -> dict:
    if not FRED_API_KEY:
        return {}
    try:
        fred = Fred(api_key=FRED_API_KEY)
    except Exception:
        return {}

    results = {}
    for spec in _lookup_industry_indicator_specs(industry, sector):
        try:
            values = _fetch_fred_series_values(fred, spec["fred_series"], MACRO_TREND_LOOKBACK_MONTHS)
        except Exception:
            continue
        if values:
            results[spec["name"]] = compute_indicator_summary(values, current_value=values[-1])
    return results


# ---------------------------------------------------------------------------
# Layer 2: sector ETF performance vs S&P 500 (yfinance historical prices)
# ---------------------------------------------------------------------------

def _nearest_close(hist, target_date) -> Optional[float]:
    idx = hist.index[hist.index <= target_date]
    if len(idx) == 0:
        return None
    return float(hist.loc[idx[-1], "Close"])


def _get_price_window(symbol: str) -> Optional[dict]:
    try:
        hist = yf.Ticker(symbol).history(period="2y")
    except Exception:
        return None
    if hist is None or hist.empty:
        return None

    if hist.index.tz is not None:
        hist.index = hist.index.tz_localize(None)

    today = hist.index[-1]
    return {
        "current": float(hist["Close"].iloc[-1]),
        "3mo_start": _nearest_close(hist, today - timedelta(days=90)),
        "6mo_start": _nearest_close(hist, today - timedelta(days=180)),
        "ytd_start": _nearest_close(hist, datetime(today.year, 1, 1)),
    }


def _compute_sector_performance(sector_etf: Optional[str]) -> Optional[dict]:
    if not sector_etf:
        return None
    sector_window = _get_price_window(sector_etf)
    benchmark_window = _get_price_window("SPY")
    if sector_window is None or benchmark_window is None:
        return None
    return compute_sector_performance(sector_window, benchmark_window)


# ---------------------------------------------------------------------------
# Layer 3 (qualitative): industry landscape via news search
# ---------------------------------------------------------------------------

def _industry_landscape(industry: Optional[str], sector: Optional[str], llm) -> dict:
    query = industry or sector or ""
    try:
        result = search_news(query, scope="industry", lookback_days=SENTIMENT_LOOKBACK_DAYS * 2)
    except Exception:
        result = {"articles": [], "source": "none", "error": "news_search raised an exception"}

    articles = result["articles"]
    if not articles:
        return {
            "competitive_summary": f"No recent industry-level news coverage was found for {query or 'this industry'}.",
            "notable_developments": [],
            "key_sources": [],
        }

    article_text = "\n".join(f"- {a.get('title')}: {a.get('summary') or ''}" for a in articles[:15])
    prompt = (
        f"{PERSONA}\n\n"
        f"Industry: {query}\n"
        f"Recent industry-level news:\n{article_text}\n\n"
        "Summarize the competitive landscape in plain language (2-4 sentences): new entrants, "
        "consolidation/M&A, regulatory shifts, or business-model changes. Then list up to 3 "
        "notable developments as short bullet points.\n\n"
        "Format:\nSUMMARY: <summary>\nDEVELOPMENTS:\n- <item>\n- <item>"
    )
    response = llm.invoke(prompt)
    text = (response.content if hasattr(response, "content") else str(response)).strip()

    summary = text
    developments = []
    in_developments = False
    for line in text.splitlines():
        stripped = line.strip()
        if stripped.upper().startswith("SUMMARY:"):
            summary = stripped.split(":", 1)[1].strip()
        elif stripped.upper().startswith("DEVELOPMENTS"):
            in_developments = True
        elif in_developments and stripped.startswith("-"):
            developments.append(stripped.lstrip("- ").strip())

    key_sources = [a.get("url") for a in articles[:5] if a.get("url")]
    return {"competitive_summary": summary, "notable_developments": developments, "key_sources": key_sources}


# ---------------------------------------------------------------------------
# Synthesis + node + A2A handler
# ---------------------------------------------------------------------------

def _interpret_macro(company_name: Optional[str], industry: Optional[str], sector: Optional[str],
                      macro_indicators: Optional[dict], sector_performance: Optional[dict],
                      industry_landscape: dict) -> str:
    llm = get_llm()
    indicators_text = "\n".join(
        f"- {name}: current={v['current']}, trend={v['trend']}"
        for name, v in (macro_indicators or {}).items()
    ) or "(unavailable)"

    if sector_performance:
        perf_text = (
            f"current={sector_performance['current']}, trend={sector_performance['trend']}, "
            f"vs S&P 500={sector_performance['vs_sp500']}"
        )
    else:
        perf_text = "(unavailable)"

    prompt = (
        f"{PERSONA}\n\n"
        f"Company: {company_name} | Industry: {industry} | Sector: {sector}\n\n"
        f"Macro indicators:\n{indicators_text}\n\n"
        f"Sector ETF performance: {perf_text}\n\n"
        f"Industry landscape: {industry_landscape.get('competitive_summary')}\n\n"
        "Write a plain-language assessment (4-6 sentences) for a beginner investor of how the "
        "broader economy, this sector's performance, and the competitive landscape might affect "
        "this company. Do not issue a buy/sell/hold recommendation."
    )
    response = llm.invoke(prompt)
    return (response.content if hasattr(response, "content") else str(response)).strip()


def macro_industry_analyst_node(state: dict) -> dict:
    """Waits on the Industry Identification node (see graph.py) for `industry`/`sector`."""
    company_name = state.get("company_name")
    industry = state.get("industry")
    sector = state.get("sector")
    now = datetime.now(timezone.utc).isoformat()

    macro_indicators = _fetch_macro_indicators()
    sector_etf = _lookup_sector_etf(sector)
    sector_performance = _compute_sector_performance(sector_etf)

    # Only the two deterministic/quantitative layers count toward a hard
    # failure -- if both are unavailable there is nothing quantitative left
    # to report. The qualitative industry-landscape layer degrades on its
    # own (see _industry_landscape) rather than failing the whole node.
    if macro_indicators is None and sector_performance is None:
        return {
            "macro_failed": True,
            "macro_indicators": None,
            "sector_performance": None,
            "industry_landscape": None,
            "macro_interpretation": None,
            "macro_data_as_of": now,
        }

    if macro_indicators is not None:
        macro_indicators.update(_fetch_industry_specific_indicators(industry, sector))

    llm = get_llm()
    landscape = _industry_landscape(industry, sector, llm)
    interpretation = _interpret_macro(company_name, industry, sector, macro_indicators, sector_performance, landscape)

    return {
        "macro_failed": False,
        "macro_indicators": macro_indicators,
        "sector_performance": sector_performance,
        "industry_landscape": landscape,
        "macro_interpretation": interpretation,
        "macro_data_as_of": now,
    }


def answer_question(question: str, state: dict) -> str:
    """
    A2A handler: answers a Checkpoint #2 follow-up question routed here
    because it's about macro conditions, sector performance, or the
    competitive/industry landscape. Grounded in this agent's own stored
    output, not re-fetched.
    """
    llm = get_llm()
    macro_indicators = state.get("macro_indicators") or {}
    indicators_text = "\n".join(
        f"- {name}: current={v['current']}, trend={v['trend']}" for name, v in macro_indicators.items()
    )
    landscape = state.get("industry_landscape") or {}
    prompt = (
        f"{PERSONA}\n\n"
        f"You previously analyzed macro/industry conditions for {state.get('company_name')} "
        f"(industry: {state.get('industry')}, sector: {state.get('sector')}):\n"
        f"Macro indicators:\n{indicators_text}\n"
        f"Sector performance: {state.get('sector_performance')}\n"
        f"Industry landscape: {landscape.get('competitive_summary')}\n"
        f"Your interpretation: {state.get('macro_interpretation')}\n\n"
        f'The user now asks a follow-up question: "{question}"\n'
        "Answer in plain language, grounded only in the research above. If the question asks "
        "for something you don't have data for, say so plainly rather than guessing."
    )
    response = llm.invoke(prompt)
    return (response.content if hasattr(response, "content") else str(response)).strip()
