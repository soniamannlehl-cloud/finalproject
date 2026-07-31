"""
News retrieval with provider failover.

Chain: NewsAPI (if keyed) -> yfinance news (keyless) -> empty.

yfinance anchors the chain because it needs no key, so news coverage works
on a fresh clone with nothing configured. An empty result is a valid
outcome, not an error -- thinly covered small-caps genuinely have no recent
news, and the calling agent reflects that in its confidence score.
"""

import logging
from datetime import datetime, timezone

import httpx
import yfinance as yf
from tenacity import retry, stop_after_attempt, wait_exponential

from ..config import get_settings

log = logging.getLogger(__name__)


def _normalize(title, publisher, link, published_at, summary=None) -> dict:
    return {
        "title": title,
        "publisher": publisher,
        "url": link,
        "published_at": published_at,
        "summary": summary,
    }


@retry(stop=stop_after_attempt(2), wait=wait_exponential(multiplier=0.5, max=3), reraise=False)
def _yfinance_news(ticker: str) -> list[dict]:
    items = yf.Ticker(ticker).news or []
    out = []
    for item in items:
        # yfinance changed this shape across versions; tolerate both.
        content = item.get("content", item)
        title = content.get("title") or item.get("title")
        if not title:
            continue

        published = content.get("pubDate") or item.get("providerPublishTime")
        if isinstance(published, (int, float)):
            published = datetime.fromtimestamp(published, tz=timezone.utc).isoformat()

        provider = content.get("provider") or {}
        publisher = (
            provider.get("displayName") if isinstance(provider, dict) else None
        ) or item.get("publisher")

        url = None
        if isinstance(content.get("canonicalUrl"), dict):
            url = content["canonicalUrl"].get("url")
        url = url or content.get("link") or item.get("link")

        out.append(_normalize(title, publisher, url, published, content.get("summary")))
    return out


def _newsapi_news(query: str) -> list[dict]:
    settings = get_settings()
    if not settings.newsapi_key:
        return []

    try:
        resp = httpx.get(
            "https://newsapi.org/v2/everything",
            params={
                "q": query, "sortBy": "publishedAt", "language": "en",
                "pageSize": 20, "apiKey": settings.newsapi_key,
            },
            timeout=settings.provider_timeout_s,
        )
        resp.raise_for_status()
        articles = resp.json().get("articles", [])
    except Exception as e:  # noqa: BLE001
        log.warning("NewsAPI unavailable, falling back: %s", e)
        return []

    return [
        _normalize(
            a.get("title"), (a.get("source") or {}).get("name"),
            a.get("url"), a.get("publishedAt"), a.get("description"),
        )
        for a in articles
    ]


def fetch_news(ticker: str, company_name: str | None = None,
               since: datetime | None = None) -> list[dict]:
    """
    Recent articles for a company, newest source first.

    Failover is silent by design: which provider answered is recorded on the
    Evidence, not surfaced as an error, because the caller cares about
    coverage volume rather than which upstream served it.
    """
    articles = _newsapi_news(company_name or ticker)

    if not articles:
        try:
            articles = _yfinance_news(ticker)
        except Exception as e:  # noqa: BLE001
            log.warning("yfinance news failed for %s: %s", ticker, e)
            articles = []

    if since is not None:
        kept = []
        for a in articles:
            published = a.get("published_at")
            if not published:
                kept.append(a)  # undated: keep rather than silently drop
                continue
            try:
                dt = datetime.fromisoformat(str(published).replace("Z", "+00:00"))
                if dt.tzinfo is None:
                    dt = dt.replace(tzinfo=timezone.utc)
                if dt >= since:
                    kept.append(a)
            except (ValueError, TypeError):
                kept.append(a)
        articles = kept

    return articles
