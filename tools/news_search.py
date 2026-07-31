"""
tools/news_search.py

Shared news search client used by both the Sentiment Analyst Agent
(scope="company") and the Macro & Industry Analyst Agent (scope="industry").

NewsAPI.org is PRIMARY. Alpha Vantage NEWS_SENTIMENT (reusing the same key
already needed for the financial-data fallback) is FALLBACK if NewsAPI
fails, isn't configured, or returns no results.
"""

from datetime import datetime, timedelta
from typing import Optional

import requests

from config import NEWSAPI_KEY, ALPHA_VANTAGE_API_KEY

# Alpha Vantage NEWS_SENTIMENT only accepts a fixed topic taxonomy (no free-text
# query) for non-ticker searches. Best-effort mapping from our industry/sector
# vocabulary to AV topics for the industry-scope fallback path; anything not
# listed here falls back to no topic filter (AV's general news feed).
_AV_INDUSTRY_TOPIC_MAP = {
    "Technology": "technology",
    "Financial Services": "finance",
    "Real Estate": "real_estate",
    "Energy": "energy_transportation",
    "Healthcare": "life_sciences",
    "Consumer Cyclical": "retail_wholesale",
    "Consumer Defensive": "retail_wholesale",
    "Industrials": "manufacturing",
}


def search_news(query: str, scope: str, ticker: Optional[str] = None, lookback_days: int = 30) -> dict:
    """
    `query`: free-text search term -- company name for scope="company",
    industry/sector name for scope="industry".
    `ticker`: stock ticker, used to sharpen the Alpha Vantage fallback query
    when scope="company" (optional, ignored for scope="industry").
    `lookback_days`: how far back to search (brief specifies ~30 days for
    sentiment; Macro/Industry analyst may pass a longer window).

    Returns {"articles": [...], "source": "newsapi" | "alpha_vantage" | "none",
             "error": str | None}
    Each article: {"title", "url", "source", "published_at", "summary"}
    """
    articles, error = _search_newsapi(query, lookback_days)
    if articles:
        return {"articles": articles, "source": "newsapi", "error": None}

    articles, fallback_error = _search_alpha_vantage(query, scope, ticker, lookback_days)
    if articles:
        return {"articles": articles, "source": "alpha_vantage", "error": None}

    return {"articles": [], "source": "none", "error": fallback_error or error or "No articles found"}


def _search_newsapi(query: str, lookback_days: int) -> tuple:
    if not NEWSAPI_KEY:
        return [], "NEWSAPI_KEY not configured"
    try:
        from_date = (datetime.utcnow() - timedelta(days=lookback_days)).strftime("%Y-%m-%d")
        resp = requests.get(
            "https://newsapi.org/v2/everything",
            params={
                "q": query,
                "from": from_date,
                "sortBy": "relevancy",
                "language": "en",
                "pageSize": 20,
                "apiKey": NEWSAPI_KEY,
            },
            timeout=10,
        )
        resp.raise_for_status()
        data = resp.json()
        articles = [
            {
                "title": a.get("title"),
                "url": a.get("url"),
                "source": (a.get("source") or {}).get("name"),
                "published_at": a.get("publishedAt"),
                "summary": a.get("description"),
            }
            for a in data.get("articles", [])
        ]
        return articles, None
    except Exception as e:
        return [], str(e)


def _search_alpha_vantage(query: str, scope: str, ticker: Optional[str], lookback_days: int) -> tuple:
    if not ALPHA_VANTAGE_API_KEY:
        return [], "ALPHA_VANTAGE_API_KEY not configured"
    try:
        params = {
            "function": "NEWS_SENTIMENT",
            "apikey": ALPHA_VANTAGE_API_KEY,
            "limit": 20,
        }
        if scope == "company" and ticker:
            params["tickers"] = ticker
        else:
            topic = _AV_INDUSTRY_TOPIC_MAP.get(query)
            if topic:
                params["topics"] = topic
            # else: no filter available -- AV returns its general news feed,
            # which the caller should treat as lower-confidence for this query

        resp = requests.get("https://www.alphavantage.co/query", params=params, timeout=10)
        resp.raise_for_status()
        data = resp.json()

        if "Note" in data or "Information" in data:
            return [], data.get("Note") or data.get("Information")

        cutoff = datetime.utcnow() - timedelta(days=lookback_days)
        articles = []
        for item in data.get("feed", []):
            published = item.get("time_published")
            published_dt = None
            if published:
                try:
                    published_dt = datetime.strptime(published, "%Y%m%dT%H%M%S")
                except ValueError:
                    published_dt = None
            if published_dt and published_dt < cutoff:
                continue
            articles.append({
                "title": item.get("title"),
                "url": item.get("url"),
                "source": item.get("source"),
                "published_at": published,
                "summary": item.get("summary"),
            })
        return articles, None
    except Exception as e:
        return [], str(e)
