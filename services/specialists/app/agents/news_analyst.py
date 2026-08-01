"""
News & Sentiment Agent.

Gathers recent coverage and characterizes sentiment. Uses yfinance's news
feed, which requires no API key, so this capability works out of the box;
NewsAPI/Tavily are wired in as richer sources when keys are present.

Low coverage is flagged deterministically rather than left to the LLM to
remember to mention. Three articles cannot support a confident sentiment
read, and the honest response is to say so and lower the confidence score --
which then flows into the evidence score and can gate the recommendation.
"""

import logging
from datetime import datetime, timedelta, timezone

from contracts import Capability, Claim, Evidence, Polarity, SourceType

from ..config import get_settings
from ..tools.news_tool import fetch_news

log = logging.getLogger(__name__)

AGENT_ID = "news_analyst_agent"

LOW_COVERAGE_THRESHOLD = 4
LOOKBACK_DAYS = 30

_SENTIMENT_PROMPT = """You are a media analyst assessing news coverage of a company.

Company: {company_name} ({ticker})
Articles from the last {days} days:
{headlines}

Summarize the sentiment in 2-4 sentences, grounded ONLY in these headlines.
Then state the overall tone on its own final line as exactly one of:
TONE: positive
TONE: negative
TONE: mixed
TONE: neutral"""


def _analyze(company_name: str, ticker: str, articles: list[dict]) -> tuple[str | None, Polarity]:
    """LLM sentiment read. Falls back to NEUTRAL polarity when unavailable."""
    settings = get_settings()
    if not settings.openai_api_key or not articles:
        return None, Polarity.NEUTRAL

    headlines = "\n".join(
        f"- {a.get('title')} ({a.get('publisher') or 'unknown'})" for a in articles[:15]
    )

    try:
        from openai import OpenAI

        client = OpenAI(api_key=settings.openai_api_key)
        response = client.chat.completions.create(
            model=settings.model_interpretation,
            temperature=settings.temperature,
            max_tokens=350,
            messages=[{
                "role": "user",
                "content": _SENTIMENT_PROMPT.format(
                    company_name=company_name, ticker=ticker,
                    days=LOOKBACK_DAYS, headlines=headlines,
                ),
            }],
        )
        text = (response.choices[0].message.content or "").strip()
    except Exception as e:  # noqa: BLE001
        log.warning("sentiment analysis unavailable: %s", e)
        return None, Polarity.NEUTRAL

    polarity = Polarity.NEUTRAL
    summary_lines = []
    for line in text.splitlines():
        if line.strip().upper().startswith("TONE:"):
            tone = line.split(":", 1)[1].strip().lower()
            polarity = {
                "positive": Polarity.BULL,
                "negative": Polarity.BEAR,
            }.get(tone, Polarity.NEUTRAL)
        else:
            summary_lines.append(line)

    return "\n".join(summary_lines).strip() or None, polarity


def handle(inputs: dict, run_id: str, task_id: str) -> tuple[list[Evidence], float, str | None, list[Claim]]:
    ticker = (inputs or {}).get("ticker")
    company_name = (inputs or {}).get("company_name") or ticker
    if not ticker:
        raise ValueError("news.sentiment requires a 'ticker' input")

    cutoff = datetime.now(timezone.utc) - timedelta(days=LOOKBACK_DAYS)
    articles = fetch_news(ticker, company_name, since=cutoff)

    # Confidence tracks coverage volume: a sentiment read from two articles
    # is genuinely less trustworthy than one from twenty, and the score
    # should reflect that rather than flattering the output.
    count = len(articles)
    degraded = None
    if count == 0:
        confidence = 0.2
        degraded = "no recent news coverage found"
    elif count < LOW_COVERAGE_THRESHOLD:
        confidence = 0.45
        degraded = f"low news coverage -- only {count} article(s) in {LOOKBACK_DAYS} days"
    else:
        confidence = min(0.9, 0.55 + 0.02 * count)

    summary, polarity = _analyze(company_name, ticker, articles)

    content = {
        "ticker": ticker,
        "article_count": count,
        "lookback_days": LOOKBACK_DAYS,
        "low_coverage": count < LOW_COVERAGE_THRESHOLD,
        "articles": articles[:15],
        "sentiment_summary": summary,
        "tone": polarity.value,
    }

    evidence = Evidence(
        evidence_id=Evidence.make_id(AGENT_ID, Capability.NEWS_SENTIMENT, content, run_id),
        run_id=run_id, task_id=task_id, agent_id=AGENT_ID,
        capability=Capability.NEWS_SENTIMENT,
        source_type=SourceType.NEWS,
        source_name="Yahoo Finance news",
        source_url=f"https://finance.yahoo.com/quote/{ticker}/news",
        citation=f"{count} article(s) covering {ticker} in the last {LOOKBACK_DAYS} days",
        content=content,
        summary=f"{count} article(s); tone: {polarity.value}",
        retrieved_at=datetime.now(timezone.utc),
        confidence=confidence,
        provider_degraded=degraded is not None,
    )

    claims: list[Claim] = []
    if summary:
        claims.append(
            Claim(
                claim_id=f"claim_{evidence.evidence_id[3:]}_sentiment",
                run_id=run_id,
                text=summary,
                evidence_ids=[evidence.evidence_id],
                confidence=confidence,
                polarity=polarity,
                category="sentiment",
                author_agent_id=AGENT_ID,
                created_at=datetime.now(timezone.utc),
            )
        )

    return [evidence], confidence, degraded, claims
