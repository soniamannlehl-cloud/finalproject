"""
agents/sentiment_analyst.py

Sentiment Analyst Agent -- evaluates news coverage and public sentiment
about the confirmed company. Runs in parallel with Industry Identification
immediately after Checkpoint #1 confirms; does not need industry/sector.
"""

from datetime import datetime, timezone

from config import get_llm, LOW_NEWS_COVERAGE_THRESHOLD, SENTIMENT_LOOKBACK_DAYS
from tools.news_search import search_news

PERSONA = (
    "You are an expert media and sentiment analyst who evaluates news "
    "coverage and public sentiment about companies."
)


def _summarize_sentiment(company_name: str, ticker: str, articles: list) -> dict:
    """
    LLM interprets the article set (titles/summaries) -- never invents
    sentiment from nothing. Returns {"summary": str, "trend": str}, where
    trend is one of positive / negative / mixed / neutral.
    """
    llm = get_llm()
    article_text = "\n".join(
        f"- {a.get('title')}: {a.get('summary') or ''}" for a in articles[:15]
    )
    prompt = (
        f"{PERSONA}\n\n"
        f"Company: {company_name} ({ticker})\n"
        f"Recent news articles (last {SENTIMENT_LOOKBACK_DAYS} days):\n{article_text}\n\n"
        "Write a short plain-language summary (3-5 sentences) of the media sentiment and "
        "public perception trend, grounded only in these articles. Then on a new line, state "
        "the overall trend as exactly one of: positive, negative, mixed, neutral.\n\n"
        "Format:\nSUMMARY: <summary>\nTREND: <one word>"
    )
    response = llm.invoke(prompt)
    text = (response.content if hasattr(response, "content") else str(response)).strip()

    summary, trend = text, "mixed"
    for line in text.splitlines():
        if line.upper().startswith("SUMMARY:"):
            summary = line.split(":", 1)[1].strip()
        elif line.upper().startswith("TREND:"):
            trend = line.split(":", 1)[1].strip().lower()
    return {"summary": summary, "trend": trend}


def sentiment_analyst_node(state: dict) -> dict:
    company_name = state.get("company_name")
    ticker = state.get("ticker")
    now = datetime.now(timezone.utc).isoformat()

    try:
        result = search_news(
            company_name or ticker, scope="company", ticker=ticker,
            lookback_days=SENTIMENT_LOOKBACK_DAYS,
        )
    except Exception:
        result = {"articles": [], "source": "none", "error": "news_search raised an exception"}

    articles = result["articles"]

    if result["source"] == "none":
        return {
            "sentiment_failed": True,
            "sentiment_summary": None,
            "key_articles": None,
            "sentiment_trend": None,
            "sentiment_data_as_of": now,
        }

    interpretation = _summarize_sentiment(company_name, ticker, articles)
    summary = interpretation["summary"]

    # Must flag low-coverage companies rather than overstate confidence --
    # enforced deterministically here rather than relying on the LLM to
    # remember to mention it.
    if len(articles) < LOW_NEWS_COVERAGE_THRESHOLD:
        summary = (
            f"⚠️ Low news coverage -- only {len(articles)} article(s) found in the last "
            f"{SENTIMENT_LOOKBACK_DAYS} days. This sentiment read has limited confidence. {summary}"
        )

    return {
        "sentiment_failed": False,
        "sentiment_summary": summary,
        "key_articles": articles[:10],
        "sentiment_trend": interpretation["trend"],
        "sentiment_data_as_of": now,
    }


def answer_question(question: str, state: dict) -> str:
    """
    A2A handler: answers a Checkpoint #2 follow-up question routed here
    because it's about sentiment/news/media coverage. Grounded in this
    agent's own stored output, not re-searched.
    """
    llm = get_llm()
    articles = state.get("key_articles") or []
    article_text = "\n".join(f"- {a.get('title')}" for a in articles[:10])
    prompt = (
        f"{PERSONA}\n\n"
        f"You previously analyzed sentiment for {state.get('company_name')} ({state.get('ticker')}):\n"
        f"Summary: {state.get('sentiment_summary')}\n"
        f"Trend: {state.get('sentiment_trend')}\n"
        f"Key articles:\n{article_text}\n\n"
        f'The user now asks a follow-up question: "{question}"\n'
        "Answer in plain language, grounded only in the research above. If the question asks "
        "for something you don't have data for, say so plainly rather than guessing."
    )
    response = llm.invoke(prompt)
    return (response.content if hasattr(response, "content") else str(response)).strip()
