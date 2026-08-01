"""
Massive (formerly Polygon.io) market data provider.

Polygon rebranded to Massive in Oct 2025. Existing API keys work on both
api.massive.com and api.polygon.io; we prefer the new domain.
"""

import logging

import httpx

from ..common.tool_client import call_with_resilience
from ..config import get_settings

log = logging.getLogger(__name__)

# New primary domain; legacy domain kept as fallback during transition.
_MASSIVE_BASE = "https://api.massive.com"
_POLYGON_BASE = "https://api.polygon.io"


def _fetch_quote(base_url: str, ticker: str, api_key: str, timeout: int) -> dict:
    resp = httpx.get(
        f"{base_url}/v2/aggs/ticker/{ticker}/prev",
        params={"apiKey": api_key},
        timeout=timeout,
    )
    resp.raise_for_status()
    return resp.json()


def get_quote(ticker: str) -> dict | None:
    """Latest price snapshot. Returns None when Massive/Polygon unavailable."""
    settings = get_settings()
    api_key = settings.polygon_api_key
    if not api_key:
        return None

    def _fetch():
        try:
            return _fetch_quote(_MASSIVE_BASE, ticker, api_key, settings.provider_timeout_s)
        except Exception as massive_err:  # noqa: BLE001
            log.info("Massive API unavailable for %s, trying legacy polygon.io: %s", ticker, massive_err)
            return _fetch_quote(_POLYGON_BASE, ticker, api_key, settings.provider_timeout_s)

    try:
        data = call_with_resilience(
            "massive", f"quote:{ticker}", _fetch,
            cache_ttl_s=settings.cache_ttl_market_data_s,
        )
    except Exception as e:  # noqa: BLE001
        log.warning("Massive/Polygon quote failed for %s: %s", ticker, e)
        return None

    results = data.get("results") or []
    if not results:
        return None

    bar = results[0]
    return {
        "ticker": ticker,
        "price": bar.get("c"),
        "open": bar.get("o"),
        "high": bar.get("h"),
        "low": bar.get("l"),
        "volume": bar.get("v"),
        "_provider": "massive",
    }
