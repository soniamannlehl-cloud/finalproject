"""
agents/financial_analyst.py

Financial Analyst Agent -- pulls raw financials (yfinance primary, Alpha
Vantage fallback), computes universal + industry-specific ratios via
deterministic functions (never LLM math), and has the LLM interpret the
already-computed results. Waits on Industry Identification for `industry`.
"""

import json
import math
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

import requests
import yfinance as yf

from config import get_llm, ALPHA_VANTAGE_API_KEY, MIN_FINANCIAL_HISTORY_DAYS
from tools.financial_calculations import compute_universal_ratios, compute_industry_ratios

PERSONA = (
    "You are an expert financial analyst who evaluates the financial health "
    "of a company using industry-appropriate financial ratios and metrics."
)

INDUSTRY_RATIOS_PATH = Path(__file__).resolve().parent.parent / "data" / "industry_ratios.json"


def _load_ratio_table() -> dict:
    with open(INDUSTRY_RATIOS_PATH, encoding="utf-8") as f:
        return json.load(f)


def _lookup_industry_ratio_names(industry: Optional[str], sector: Optional[str]) -> list:
    table = _load_ratio_table()
    return (
        table["industry_ratio_sets"].get(industry)
        or table["sector_defaults"].get(sector)
        or table["unknown_default"]
    )


# ---------------------------------------------------------------------------
# yfinance extraction (PRIMARY)
# ---------------------------------------------------------------------------

def _row(df, label: str, col_idx: int = 0) -> Optional[float]:
    try:
        if df is None or df.empty or label not in df.index:
            return None
        val = df.loc[label].iloc[col_idx]
        if val is None or (isinstance(val, float) and math.isnan(val)):
            return None
        return float(val)
    except Exception:
        return None


def _pull_yfinance_raw(ticker: str) -> Optional[dict]:
    try:
        t = yf.Ticker(ticker)
        info = t.info or {}
        bs = t.balance_sheet
        inc = t.income_stmt
        cf = t.cashflow
    except Exception:
        return None

    price = info.get("currentPrice") or info.get("regularMarketPrice")
    revenue = _row(inc, "Total Revenue", 0) or info.get("totalRevenue")

    if price is None and revenue is None:
        return None  # nothing usable came back

    operating_cash_flow = _row(cf, "Operating Cash Flow", 0) or info.get("operatingCashflow")
    capital_expenditures = _row(cf, "Capital Expenditure", 0)
    if capital_expenditures is None and operating_cash_flow is not None and info.get("freeCashflow") is not None:
        capital_expenditures = operating_cash_flow - info["freeCashflow"]

    raw = {
        "price": price,
        "shares_outstanding": info.get("sharesOutstanding"),
        "market_cap": info.get("marketCap"),
        "net_income": _row(inc, "Net Income", 0) or info.get("netIncomeToCommon"),
        "eps": info.get("trailingEps"),
        "revenue": revenue,
        "revenue_prior_year": _row(inc, "Total Revenue", 1),
        "gross_profit": _row(inc, "Gross Profit", 0) or info.get("grossProfits"),
        "operating_income": _row(inc, "Operating Income", 0),
        "ebitda": _row(inc, "EBITDA", 0) or info.get("ebitda"),
        "total_debt": _row(bs, "Total Debt", 0) or info.get("totalDebt"),
        "total_equity": _row(bs, "Stockholders Equity", 0),
        "total_equity_prior_year": _row(bs, "Stockholders Equity", 1),
        "total_assets": _row(bs, "Total Assets", 0),
        "total_assets_prior_year": _row(bs, "Total Assets", 1),
        "current_assets": _row(bs, "Current Assets", 0),
        "current_liabilities": _row(bs, "Current Liabilities", 0),
        "inventory": _row(bs, "Inventory", 0),
        "interest_expense": _row(inc, "Interest Expense", 0),
        "rd_expense": _row(inc, "Research And Development", 0),
        "operating_expenses": _row(inc, "Operating Expense", 0),
        "dividends_paid": _row(cf, "Cash Dividends Paid", 0),
        "operating_cash_flow": operating_cash_flow,
        "capital_expenditures": capital_expenditures,
    }

    statement_periods = len(inc.columns) if inc is not None and not inc.empty else 0
    latest_period_date = inc.columns[0].to_pydatetime() if statement_periods else None

    return {
        "raw": raw,
        "statement_periods": statement_periods,
        "latest_period_date": latest_period_date,
        "industry": info.get("industry"),
        "sector": info.get("sector"),
    }


# ---------------------------------------------------------------------------
# Alpha Vantage extraction (FALLBACK)
# ---------------------------------------------------------------------------

def _av_get(function: str, ticker: str) -> Optional[dict]:
    resp = requests.get(
        "https://www.alphavantage.co/query",
        params={"function": function, "symbol": ticker, "apikey": ALPHA_VANTAGE_API_KEY},
        timeout=10,
    )
    resp.raise_for_status()
    data = resp.json()
    if not data or "Note" in data or "Information" in data or "Error Message" in data:
        return None
    return data


def _av_float(d: dict, key: str) -> Optional[float]:
    try:
        val = d.get(key)
        if val in (None, "None", "-", ""):
            return None
        return float(val)
    except Exception:
        return None


def _pull_alpha_vantage_raw(ticker: str) -> Optional[dict]:
    if not ALPHA_VANTAGE_API_KEY:
        return None
    try:
        overview = _av_get("OVERVIEW", ticker)
        if not overview or not overview.get("Symbol"):
            return None
        balance = _av_get("BALANCE_SHEET", ticker) or {}
        income = _av_get("INCOME_STATEMENT", ticker) or {}
        cashflow = _av_get("CASH_FLOW", ticker) or {}
        quote = _av_get("GLOBAL_QUOTE", ticker) or {}
    except Exception:
        return None

    bs_reports = balance.get("annualReports", [])
    inc_reports = income.get("annualReports", [])
    cf_reports = cashflow.get("annualReports", [])
    bs0 = bs_reports[0] if bs_reports else {}
    bs1 = bs_reports[1] if len(bs_reports) > 1 else {}
    inc0 = inc_reports[0] if inc_reports else {}
    inc1 = inc_reports[1] if len(inc_reports) > 1 else {}
    cf0 = cf_reports[0] if cf_reports else {}

    price = None
    gq = quote.get("Global Quote", {})
    try:
        price = float(gq.get("05. price"))
    except (TypeError, ValueError):
        price = None

    raw = {
        "price": price,
        "shares_outstanding": _av_float(overview, "SharesOutstanding"),
        "market_cap": _av_float(overview, "MarketCapitalization"),
        "net_income": _av_float(inc0, "netIncome"),
        "eps": _av_float(overview, "EPS"),
        "revenue": _av_float(inc0, "totalRevenue") or _av_float(overview, "RevenueTTM"),
        "revenue_prior_year": _av_float(inc1, "totalRevenue"),
        "gross_profit": _av_float(inc0, "grossProfit") or _av_float(overview, "GrossProfitTTM"),
        "operating_income": _av_float(inc0, "operatingIncome"),
        "ebitda": _av_float(inc0, "ebitda") or _av_float(overview, "EBITDA"),
        "total_debt": _av_float(bs0, "shortLongTermDebtTotal"),
        "total_equity": _av_float(bs0, "totalShareholderEquity"),
        "total_equity_prior_year": _av_float(bs1, "totalShareholderEquity"),
        "total_assets": _av_float(bs0, "totalAssets"),
        "total_assets_prior_year": _av_float(bs1, "totalAssets"),
        "current_assets": _av_float(bs0, "totalCurrentAssets"),
        "current_liabilities": _av_float(bs0, "totalCurrentLiabilities"),
        "inventory": _av_float(bs0, "inventory"),
        "interest_expense": _av_float(inc0, "interestExpense"),
        "rd_expense": _av_float(inc0, "researchAndDevelopment"),
        "operating_expenses": _av_float(inc0, "operatingExpenses"),
        "dividends_paid": _av_float(cf0, "dividendPayout"),
        "operating_cash_flow": _av_float(cf0, "operatingCashflow"),
        "capital_expenditures": _av_float(cf0, "capitalExpenditures"),
    }

    latest_period_date = None
    fiscal_date_str = inc0.get("fiscalDateEnding")
    if fiscal_date_str:
        try:
            latest_period_date = datetime.strptime(fiscal_date_str, "%Y-%m-%d")
        except ValueError:
            latest_period_date = None

    # AV's OVERVIEW "Sector"/"Industry" fields use a different taxonomy/casing
    # than yfinance (which data/industry_ratios.json is keyed on), so they
    # would not match the lookup table anyway -- left None to fall through
    # to unknown_default rather than feed in values that look plausible but
    # never match.
    return {
        "raw": raw,
        "statement_periods": len(inc_reports),
        "latest_period_date": latest_period_date,
        "industry": None,
        "sector": None,
    }


# ---------------------------------------------------------------------------
# Data quality: flag incomplete/stale filings rather than silently compute
# misleading ratios off partial data (recent IPOs, foreign issuers)
# ---------------------------------------------------------------------------

def _assess_data_quality(pull: dict) -> dict:
    periods = pull.get("statement_periods", 0)
    latest_date = pull.get("latest_period_date")

    incomplete = periods < 2
    stale = False
    if latest_date is not None:
        age_days = (datetime.now(timezone.utc) - latest_date.replace(tzinfo=timezone.utc)).days
        stale = age_days > MIN_FINANCIAL_HISTORY_DAYS

    note = None
    if incomplete and stale:
        note = (
            "Limited filing history and the most recent statement is over a year old -- "
            "likely a recent IPO or foreign issuer with sparse reporting."
        )
    elif incomplete:
        note = (
            "Only one reporting period is available -- likely a recent IPO. "
            "Year-over-year comparisons are not yet possible."
        )
    elif stale:
        note = "The most recent financial statement on file is over a year old -- ratios may not reflect current conditions."

    return {"stale": stale, "incomplete": incomplete, "note": note}


# ---------------------------------------------------------------------------
# LLM interpretation of already-computed ratios (never recomputes them)
# ---------------------------------------------------------------------------

def _format_ratios(ratios: dict) -> str:
    lines = []
    for name, r in ratios.items():
        if r["meaningful"]:
            lines.append(f"- {name}: {r['formatted']}")
        else:
            lines.append(f"- {name}: not meaningful ({r['flag']})")
    return "\n".join(lines) if lines else "(none)"


def _interpret_financials(company_name: str, ticker: str, universal: dict,
                           industry_ratios: dict, quality_note: Optional[str]) -> str:
    llm = get_llm()
    quality_block = f"\n\nDATA QUALITY NOTE: {quality_note}" if quality_note else ""
    prompt = (
        f"{PERSONA}\n\n"
        f"Company: {company_name} ({ticker})\n\n"
        f"Universal financial ratios (already computed, not by you):\n{_format_ratios(universal)}\n\n"
        f"Industry-specific ratios for this company's sector (already computed, not by you):\n"
        f"{_format_ratios(industry_ratios)}"
        f"{quality_block}\n\n"
        "Interpret these ALREADY-COMPUTED numbers -- do not recompute or second-guess the "
        "arithmetic. Write a plain-language assessment (4-6 sentences) of this company's "
        "financial health for a beginner investor. If any ratios are flagged 'not meaningful', "
        "briefly explain why in plain terms rather than ignoring them."
    )
    response = llm.invoke(prompt)
    return (response.content if hasattr(response, "content") else str(response)).strip()


# ---------------------------------------------------------------------------
# Node + A2A handler
# ---------------------------------------------------------------------------

def financial_analyst_node(state: dict) -> dict:
    """
    Runs in parallel with Sentiment Analyst and Macro & Industry Analyst
    (flat 3-way fan-out from Checkpoint #1 -- see graph.py). Since parallel
    sibling nodes can't see each other's writes within the same step, this
    node resolves industry/sector itself (already-fetched data from its own
    yfinance pull, effectively free) rather than depending on a separate
    upstream "Industry Identification" node.
    """
    ticker = state.get("ticker")
    company_name = state.get("company_name")
    now = datetime.now(timezone.utc).isoformat()

    pull = _pull_yfinance_raw(ticker)
    if pull is None:
        pull = _pull_alpha_vantage_raw(ticker)

    if pull is None:
        return {
            "financial_failed": True,
            "raw_financials": None,
            "universal_ratios": None,
            "industry_ratios": None,
            "ratio_interpretation": None,
            "financial_data_as_of": now,
        }

    raw = pull["raw"]
    industry = pull.get("industry")
    sector = pull.get("sector")
    quality = _assess_data_quality(pull)

    universal = compute_universal_ratios(raw)
    ratio_names = _lookup_industry_ratio_names(industry, sector)
    industry_ratio_results = compute_industry_ratios(raw, ratio_names)

    interpretation = _interpret_financials(company_name, ticker, universal, industry_ratio_results, quality["note"])
    if quality["note"]:
        interpretation = f"⚠️ {quality['note']} {interpretation}"

    return {
        "financial_failed": False,
        "raw_financials": raw,
        "universal_ratios": universal,
        "industry_ratios": industry_ratio_results,
        "ratio_interpretation": interpretation,
        "financial_data_as_of": now,
        "industry": industry,
        "sector": sector,
    }


def answer_question(question: str, state: dict) -> str:
    """
    A2A handler: answers a Checkpoint #2 follow-up question routed here
    because it's about financial ratios/earnings/valuation. Grounded in
    this agent's own stored output, never recomputed.
    """
    llm = get_llm()
    universal = state.get("universal_ratios") or {}
    industry_ratios = state.get("industry_ratios") or {}
    prompt = (
        f"{PERSONA}\n\n"
        f"You previously analyzed the financials of {state.get('company_name')} ({state.get('ticker')}):\n"
        f"Universal ratios:\n{_format_ratios(universal)}\n"
        f"Industry ratios:\n{_format_ratios(industry_ratios)}\n"
        f"Your interpretation: {state.get('ratio_interpretation')}\n\n"
        f'The user now asks a follow-up question: "{question}"\n'
        "Answer in plain language, grounded only in the research above. If the question asks "
        "for something you don't have data for, say so plainly rather than guessing."
    )
    response = llm.invoke(prompt)
    return (response.content if hasattr(response, "content") else str(response)).strip()
