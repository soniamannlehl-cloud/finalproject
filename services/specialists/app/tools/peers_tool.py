"""
Industry peer discovery and comparable metrics.

Peer selection matters because a valuation multiple is meaningless in
isolation: 30x earnings is cheap for one industry and expensive for another.
Peers come from yfinance's industry/sector constituents rather than a hand-curated
list, so coverage extends to any industry without maintenance.
"""

import logging

import yfinance as yf
from tenacity import retry, stop_after_attempt, wait_exponential

log = logging.getLogger(__name__)

# When yfinance industry slugs fail, use known comparables for common industries.
_FALLBACK_PEERS: dict[str, list[str]] = {
    "internet content": ["GOOGL", "SNAP", "PINS", "RDDT", "BABA"],
    "interactive media": ["GOOGL", "SNAP", "PINS", "RDDT"],
    "software": ["MSFT", "ORCL", "CRM", "ADBE", "NOW"],
    "semiconductor": ["NVDA", "AMD", "INTC", "AVGO", "QCOM"],
    "consumer electronics": ["AAPL", "SONY", "HPQ", "DELL"],
    "banks": ["JPM", "BAC", "WFC", "C", "GS"],
}


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


def _sector_key(sector: str) -> str:
    return _industry_key(sector)


def _key_variants(label: str) -> list[str]:
    """Try a few slug variants — Yahoo naming is inconsistent."""
    base = _industry_key(label)
    variants = [base]
    if "and" in base:
        variants.append(base.replace("-and-", "-"))
    if base.endswith("-information"):
        variants.append(base.replace("-information", ""))
    return list(dict.fromkeys(variants))


def _peers_from_top_companies(top, exclude_ticker: str, limit: int) -> list[dict]:
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


def _fallback_peers(industry: str, exclude_ticker: str, limit: int) -> list[dict]:
    key = (industry or "").lower()
    for pattern, tickers in _FALLBACK_PEERS.items():
        if pattern in key:
            peers = []
            for t in tickers:
                if t.upper() == exclude_ticker.upper():
                    continue
                peers.append({"ticker": t, "name": t, "market_weight": 0.0})
                if len(peers) >= limit:
                    break
            if peers:
                log.info("using fallback peer set for industry %r", industry)
                return peers
    return []


@retry(stop=stop_after_attempt(2), wait=wait_exponential(multiplier=0.5, max=3), reraise=True)
def _fetch_top_companies(industry_key: str):
    return yf.Industry(industry_key).top_companies


@retry(stop=stop_after_attempt(2), wait=wait_exponential(multiplier=0.5, max=3), reraise=True)
def _fetch_sector_companies(sector_key: str):
    return yf.Sector(sector_key).top_companies


def get_industry_peers(
    industry: str,
    exclude_ticker: str,
    limit: int = 6,
    sector: str | None = None,
) -> list[dict]:
    """
    Constituents of the company's industry, largest first, excluding itself.

    Falls back to sector constituents, then a static peer map for common
    industries when Yahoo slug lookup fails.
    """
    if industry:
        for key in _key_variants(industry):
            try:
                peers = _peers_from_top_companies(_fetch_top_companies(key), exclude_ticker, limit)
                if peers:
                    return peers
            except Exception as e:  # noqa: BLE001
                log.info("peer lookup failed for industry key %r: %s", key, e)

    if sector:
        for key in _key_variants(sector):
            try:
                peers = _peers_from_top_companies(_fetch_sector_companies(key), exclude_ticker, limit)
                if peers:
                    log.info("peer lookup succeeded via sector %r", sector)
                    return peers
            except Exception as e:  # noqa: BLE001
                log.info("sector peer lookup failed for %r: %s", key, e)

    return _fallback_peers(industry or sector or "", exclude_ticker, limit)


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
