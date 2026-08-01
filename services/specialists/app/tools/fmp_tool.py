"""
Financial Modeling Prep (FMP) data provider.

Uses FMP's stable API (required for accounts created after Aug 2025).
Legacy /api/v3/ endpoints return 403 for new subscribers.
Falls back to yfinance when unavailable.
"""

import logging

import httpx

from ..common.tool_client import call_with_resilience
from ..config import get_settings

log = logging.getLogger(__name__)

_BASE = "https://financialmodelingprep.com/stable"


def _get(endpoint: str, params: dict | None = None) -> list | dict:
    settings = get_settings()
    if not settings.fmp_api_key:
        return []

    def _fetch():
        p = dict(params or {})
        p["apikey"] = settings.fmp_api_key
        resp = httpx.get(f"{_BASE}/{endpoint}", params=p, timeout=settings.provider_timeout_s)
        resp.raise_for_status()
        data = resp.json()
        if isinstance(data, dict) and "Error Message" in data:
            raise RuntimeError(data["Error Message"])
        return data

    return call_with_resilience(
        "fmp", endpoint, _fetch,
        cache_ttl_s=86400 * 7 if settings.cache_ttl_immutable_s == 0 else settings.cache_ttl_immutable_s,
    )


def get_financials(ticker: str) -> dict | None:
    """
    Normalized financial inputs compatible with financial_calculations.py.

    Returns None when FMP is unavailable so callers can fall back.
    """
    settings = get_settings()
    if not settings.fmp_api_key:
        return None

    base_params = {"symbol": ticker}

    try:
        profile = _get("profile", base_params)
        income = _get("income-statement", {**base_params, "limit": 2})
        balance = _get("balance-sheet-statement", {**base_params, "limit": 1})
        cash = _get("cash-flow-statement", {**base_params, "limit": 1})
    except Exception as e:  # noqa: BLE001
        log.warning("FMP financials failed for %s: %s", ticker, e)
        return None

    if not income or not isinstance(income, list):
        return None

    latest = income[0]
    prior = income[1] if len(income) > 1 else {}
    bal = balance[0] if isinstance(balance, list) and balance else {}
    cf = cash[0] if isinstance(cash, list) and cash else {}
    prof = profile[0] if isinstance(profile, list) and profile else {}

    return {
        "ticker": ticker,
        "currency": prof.get("currency") or latest.get("reportedCurrency"),
        "price": prof.get("price"),
        "market_cap": prof.get("mktCap") or prof.get("marketCap") or latest.get("marketCap"),
        "enterprise_value": None,
        "shares_outstanding": latest.get("weightedAverageShsOut"),
        "eps": latest.get("eps"),
        "book_value_per_share": None,
        "revenue": latest.get("revenue"),
        "revenue_prior": prior.get("revenue"),
        "gross_profit": latest.get("grossProfit"),
        "operating_income": latest.get("operatingIncome"),
        "net_income": latest.get("netIncome"),
        "ebitda": latest.get("ebitda"),
        "total_debt": bal.get("totalDebt"),
        "total_equity": bal.get("totalStockholdersEquity"),
        "total_assets": bal.get("totalAssets"),
        "current_assets": bal.get("totalCurrentAssets"),
        "current_liabilities": bal.get("totalCurrentLiabilities"),
        "operating_cash_flow": cf.get("operatingCashFlow"),
        "capex": cf.get("capitalExpenditure"),
        "statement_periods": len(income),
        "latest_period": latest.get("date"),
        "_provider": "fmp",
    }
