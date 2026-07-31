"""
Industry peer discovery and comparable metrics.

Peer selection matters because a valuation multiple is meaningless in
isolation: 30x earnings is cheap for one industry and expensive for another.
Peers come from yfinance's industry constituents rather than a hand-curated
list, so coverage extends to any industry without maintenance.
"""

import logging

import yfinance as yf
from tenacity import retry, stop_after_attempt, wait_exponential

log = logging.getLogger(__name__)


def _industry_key(industry: str) -> str:
    """
    yfinance keys industries as lowercase hyphenated slugs.

    Yahoo's industry labels contain typographic dashes -- "Drug
    Manufacturers—General" uses an EM DASH, not a hyphen. Normalizing those
    to ASCII hyphens first is required; without it the slug 404s and peer
    lookup silently returns nothing for entire sectors.
    """
    normalized = (
        industry.lower()
        .replace("—", "-")  # em dash
        .replace("–", "-")  # en dash
        .replace("&", "and")
        .replace("/", "-")
        .replace(",", "")
        .replace(" ", "-")
    )
    while "--" in normalized:
        normalized = normalized.replace("--", "-")
    return normalized.strip("-")


@retry(stop=stop_after_attempt(2), wait=wait_exponential(multiplier=0.5, max=3), reraise=True)
def _fetch_top_companies(industry_key: str):
    return yf.Industry(industry_key).top_companies


def get_industry_peers(industry: str, exclude_ticker: str, limit: int = 6) -> list[dict]:
    """
    Constituents of the company's industry, largest first, excluding itself.

    Returns an empty list when the industry is unrecognized -- reported as a
    declared gap rather than silently substituting an unrelated peer set,
    which would produce comparisons that look rigorous and mean nothing.
    """
    if not industry:
        return []

    try:
        top = _fetch_top_companies(_industry_key(industry))
    except Exception as e:  # noqa: BLE001
        log.info("peer lookup failed for industry %r: %s", industry, e)
        return []

    if top is None or getattr(top, "empty", True):
        return []

    peers = []
    for symbol, row in top.iterrows():
        if symbol.upper() == exclude_ticker.upper() or len(peers) >= limit:
            continue
        peers.append({
            "ticker": symbol,
            "name": row.get("name"),
            "market_weight": float(row.get("market weight") or 0.0),
            "analyst_rating": row.get("rating") if isinstance(row.get("rating"), str) else None,
        })
    return peers


def get_peer_metrics(tickers: list[str]) -> dict[str, dict]:
    """
    Comparable valuation and margin metrics for peers.

    Uses `.info` rather than full statements: this is a relative-positioning
    exercise across several companies, and pulling complete statements for
    each would multiply latency for precision the comparison doesn't need.
    """
    metrics: dict[str, dict] = {}
    for ticker in tickers:
        try:
            info = yf.Ticker(ticker).info or {}
        except Exception as e:  # noqa: BLE001
            log.info("peer metrics unavailable for %s: %s", ticker, e)
            continue

        metrics[ticker] = {
            "name": info.get("shortName"),
            "market_cap": info.get("marketCap"),
            "trailing_pe": info.get("trailingPE"),
            "forward_pe": info.get("forwardPE"),
            "price_to_book": info.get("priceToBook"),
            "ev_to_revenue": info.get("enterpriseToRevenue"),
            "ev_to_ebitda": info.get("enterpriseToEbitda"),
            "gross_margin": info.get("grossMargins"),
            "operating_margin": info.get("operatingMargins"),
            "profit_margin": info.get("profitMargins"),
            "revenue_growth": info.get("revenueGrowth"),
            "return_on_equity": info.get("returnOnEquity"),
        }
    return metrics


def median(values: list[float | None]) -> float | None:
    """
    Median of the values that exist.

    Median rather than mean because peer multiples are routinely skewed by a
    single company with near-zero earnings producing a 900x P/E, which would
    drag a mean into uselessness.
    """
    clean = sorted(v for v in values if v is not None and v == v and v > 0)
    if not clean:
        return None
    mid = len(clean) // 2
    if len(clean) % 2:
        return clean[mid]
    return (clean[mid - 1] + clean[mid]) / 2
