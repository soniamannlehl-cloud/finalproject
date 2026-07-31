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
