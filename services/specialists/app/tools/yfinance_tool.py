"""
yfinance data provider.

Anchors every fallback chain in the platform because it requires no API key
-- the system stays demonstrable with zero paid subscriptions. Wrapped in
retry/timeout because yfinance scrapes an undocumented endpoint and fails
intermittently under load.

All functions here return plain dicts. Converting provider output into
`Evidence` is the agent's job, not the tool's -- tools know about providers,
agents know about the domain.
"""

import logging
from dataclasses import dataclass

import yfinance as yf
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential

log = logging.getLogger(__name__)


class ProviderError(RuntimeError):
    """Raised when a provider cannot serve a request. Callers convert this
    into a degraded/failed TaskResult rather than letting it propagate."""


@dataclass(frozen=True)
class CompanyMatch:
    """One candidate company returned by a ticker/name search."""

    ticker: str
    name: str
    exchange: str | None
    quote_type: str
    sector: str | None
    industry: str | None
    score: float

    def to_dict(self) -> dict:
        return {
            "ticker": self.ticker,
            "name": self.name,
            "exchange": self.exchange,
            "quote_type": self.quote_type,
            "sector": self.sector,
            "industry": self.industry,
            "score": self.score,
        }


# Yahoo returns listings from every global exchange. US primary listings are
# preferred so "Tesla" resolves to TSLA rather than a Frankfurt cross-listing.
_PREFERRED_EXCHANGES = {"NMS", "NYQ", "NGM", "ASE", "PCX", "BTS"}


@retry(
    retry=retry_if_exception_type(Exception),
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=0.5, min=0.5, max=4),
    reraise=True,
)
def _raw_search(query: str, max_results: int) -> list[dict]:
    return yf.Search(query, max_results=max_results).quotes or []


def search_companies(query: str, max_results: int = 10) -> list[CompanyMatch]:
    """
    Resolve free text to candidate public companies, best match first.

    Returns an empty list when nothing matches -- that is a valid answer
    (the input may name a private company), not an error condition.
    """
    query = (query or "").strip()
    if not query:
        return []

    try:
        raw = _raw_search(query, max_results)
    except Exception as e:  # noqa: BLE001
        raise ProviderError(f"yfinance search failed for {query!r}: {e}") from e

    matches: list[CompanyMatch] = []
    for q in raw:
        # EQUITY only: ETFs, indices, and futures are not companies to research.
        if q.get("quoteType") != "EQUITY":
            continue
        ticker, name = q.get("symbol"), q.get("shortname") or q.get("longname")
        if not ticker or not name:
            continue
        matches.append(
            CompanyMatch(
                ticker=ticker,
                name=name,
                exchange=q.get("exchange"),
                quote_type=q.get("quoteType"),
                sector=q.get("sector"),
                industry=q.get("industry"),
                score=float(q.get("score") or 0.0),
            )
        )

    # Rank US primary listings above cross-listings, then by Yahoo's score.
    matches.sort(key=lambda m: (m.exchange not in _PREFERRED_EXCHANGES, -m.score))
    return matches


@retry(
    retry=retry_if_exception_type(Exception),
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=0.5, min=0.5, max=4),
    reraise=True,
)
def _raw_info(ticker: str) -> dict:
    return yf.Ticker(ticker).info or {}


def get_company_profile(ticker: str) -> dict:
    """
    Fetch identifying/classification fields for a confirmed ticker.

    Deliberately narrow: this returns what the platform needs to classify a
    company and select an industry playbook, not the full ~150-field blob
    yfinance exposes.
    """
    try:
        info = _raw_info(ticker)
    except Exception as e:  # noqa: BLE001
        raise ProviderError(f"yfinance profile failed for {ticker!r}: {e}") from e

    if not info or not info.get("symbol"):
        raise ProviderError(f"yfinance returned no profile for {ticker!r}")

    return {
        "ticker": info.get("symbol"),
        "name": info.get("longName") or info.get("shortName"),
        "sector": info.get("sector"),
        "industry": info.get("industry"),
        "exchange": info.get("exchange"),
        "country": info.get("country"),
        "currency": info.get("currency"),
        "market_cap": info.get("marketCap"),
        "employees": info.get("fullTimeEmployees"),
        "website": info.get("website"),
        "summary": info.get("longBusinessSummary"),
        "quote_type": info.get("quoteType"),
    }


@retry(
    retry=retry_if_exception_type(Exception),
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=0.5, min=0.5, max=4),
    reraise=True,
)
def _raw_financials(ticker: str) -> tuple[dict, object, object, object]:
    t = yf.Ticker(ticker)
    return t.info or {}, t.income_stmt, t.balance_sheet, t.cashflow


def _cell(df, label: str, col: int = 0) -> float | None:
    """
    Read one value from a yfinance statement frame.

    Returns None rather than raising for any of the many ways this can be
    absent (missing row, short history, NaN) so callers can treat "not
    reported" uniformly.
    """
    try:
        if df is None or getattr(df, "empty", True) or label not in df.index:
            return None
        value = df.loc[label].iloc[col]
        if value is None:
            return None
        f = float(value)
        return None if f != f else f  # NaN check without importing math
    except Exception:  # noqa: BLE001
        return None


def get_financials(ticker: str) -> dict:
    """
    Normalized financial inputs for the deterministic ratio calculations.

    Chain: FMP (if keyed) -> yfinance.
    """
    from . import fmp_tool

    fmp_data = fmp_tool.get_financials(ticker)
    if fmp_data:
        return fmp_data

    from . import polygon_tool

    poly = polygon_tool.get_quote(ticker)
    price_override = poly.get("price") if poly else None

    try:
        info, income, balance, cash = _raw_financials(ticker)
    except Exception as e:  # noqa: BLE001
        raise ProviderError(f"yfinance financials failed for {ticker!r}: {e}") from e

    revenue = _cell(income, "Total Revenue") or info.get("totalRevenue")
    if revenue is None and not info:
        raise ProviderError(f"no financial data available for {ticker!r}")

    ocf = _cell(cash, "Operating Cash Flow") or info.get("operatingCashflow")
    capex = _cell(cash, "Capital Expenditure")
    if capex is None and ocf is not None and info.get("freeCashflow") is not None:
        capex = ocf - info["freeCashflow"]

    shares = info.get("sharesOutstanding")
    equity = _cell(balance, "Stockholders Equity")
    book_value_per_share = info.get("bookValue")
    if book_value_per_share is None and equity and shares:
        book_value_per_share = equity / shares

    periods = len(income.columns) if income is not None and not income.empty else 0
    latest_period = (
        income.columns[0].to_pydatetime().isoformat() if periods else None
    )

    return {
        "ticker": ticker,
        "currency": info.get("currency"),
        "price": price_override or info.get("currentPrice") or info.get("regularMarketPrice"),
        "market_cap": info.get("marketCap"),
        "enterprise_value": info.get("enterpriseValue"),
        "shares_outstanding": shares,
        "eps": info.get("trailingEps"),
        "book_value_per_share": book_value_per_share,
        "revenue": revenue,
        "revenue_prior": _cell(income, "Total Revenue", 1),
        "gross_profit": _cell(income, "Gross Profit") or info.get("grossProfits"),
        "operating_income": _cell(income, "Operating Income"),
        "net_income": _cell(income, "Net Income") or info.get("netIncomeToCommon"),
        "ebitda": _cell(income, "EBITDA") or info.get("ebitda"),
        "total_debt": _cell(balance, "Total Debt") or info.get("totalDebt"),
        "total_equity": equity,
        "total_assets": _cell(balance, "Total Assets"),
        "current_assets": _cell(balance, "Current Assets"),
        "current_liabilities": _cell(balance, "Current Liabilities"),
        "operating_cash_flow": ocf,
        "capex": capex,
        "statement_periods": periods,
        "latest_period": latest_period,
    }
