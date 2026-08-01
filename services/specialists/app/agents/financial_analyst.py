"""
Financial Analyst Agent.

Serves two capabilities:
  financials.statements  raw normalized statement data
  financials.ratios      computed metrics + a plain-language interpretation

The division of labor is strict and load-bearing: every number is computed
by `tools/financial_calculations.py` in Python, and the LLM receives only
already-computed values to interpret. It never sees raw inputs it could do
arithmetic on, and its output is prose, not figures. A model asked to
compute P/E will produce a plausible wrong number; a model asked to explain
a P/E of 32.4 cannot corrupt the 32.4.
"""

import logging
from datetime import datetime, timezone

from contracts import Capability, Claim, Evidence, Polarity, SourceType

from ..config import get_settings
from ..tools.financial_calculations import compute_metrics
from ..tools.yfinance_tool import get_financials

log = logging.getLogger(__name__)

AGENT_ID = "financial_analyst_agent"

def _fmt_money(value: float | None) -> str:
    if value is None:
        return "n/a"
    for unit, scale in (("T", 1e12), ("B", 1e9), ("M", 1e6)):
        if abs(value) >= scale:
            return f"${value / scale:.2f}{unit}"
    return f"${value:,.0f}"


_INTERPRET_PROMPT = """You are a senior financial analyst reviewing ALREADY-COMPUTED metrics for a {industry_label} company.

Company: {company_name} ({ticker})
Business model context: {business_model}

Computed metrics (do NOT recompute or dispute these numbers):
{metrics}

Write 3-5 sentences assessing this company's financial health using the industry-appropriate lens above. Rules:
- Interpret the numbers given; never state a figure that is not listed above.
- Where a metric is marked "not meaningful", explain briefly why that matters for this industry.
- Be balanced: note both strengths and weaknesses.
- Do not give investment advice or a buy/sell view."""


def _format_metrics(metrics: dict) -> str:
    lines = []
    for name, m in metrics.items():
        if m["meaningful"]:
            lines.append(f"- {name}: {m['formatted']}")
        else:
            lines.append(f"- {name}: not meaningful ({m['flag']})")
    return "\n".join(lines)


def _interpret(company_name: str, ticker: str, metrics: dict, profile: dict | None = None) -> str | None:
    """
    LLM interpretation of computed metrics. Returns None if unavailable.

    Absence degrades the output rather than failing the task: the metrics
    themselves are the evidence, and they stand on their own.
    """
    settings = get_settings()
    if not settings.openai_api_key:
        return None

    try:
        from openai import OpenAI

        client = OpenAI(api_key=settings.openai_api_key)
        response = client.chat.completions.create(
            model=settings.model_interpretation,
            temperature=settings.temperature,
            max_tokens=400,
            messages=[{
                "role": "user",
                "content": _INTERPRET_PROMPT.format(
                    company_name=company_name, ticker=ticker,
                    metrics=_format_metrics(metrics),
                    industry_label=(profile or {}).get("display_name", "general"),
                    business_model=(profile or {}).get("business_model", "operating company"),
                ),
            }],
        )
        return (response.choices[0].message.content or "").strip() or None
    except Exception as e:  # noqa: BLE001
        log.warning("financial interpretation unavailable: %s", e)
        return None


def _data_quality(financials: dict) -> tuple[float, str | None]:
    """
    Score completeness and flag thin filing history.

    A recent IPO with one reporting period cannot support growth analysis,
    and computing it anyway off a single year produces a confident artifact.
    """
    key_fields = ("revenue", "net_income", "total_equity", "operating_cash_flow", "price")
    present = sum(1 for k in key_fields if financials.get(k) is not None)
    completeness = present / len(key_fields)

    periods = financials.get("statement_periods", 0)
    if periods < 2:
        return round(0.5 * completeness, 2), (
            "only one reporting period available -- year-over-year comparisons "
            "are not possible (likely a recent IPO)"
        )
    if completeness < 1.0:
        return round(0.6 + 0.4 * completeness, 2), "some financial statement fields were not reported"
    return 0.95, None


def _statements_evidence(run_id: str, task_id: str, ticker: str, financials: dict, confidence: float) -> Evidence:
    return Evidence(
        evidence_id=Evidence.make_id(AGENT_ID, Capability.FINANCIAL_STATEMENTS, financials, run_id),
        run_id=run_id, task_id=task_id, agent_id=AGENT_ID,
        capability=Capability.FINANCIAL_STATEMENTS,
        source_type=SourceType.FINANCIAL_STATEMENT,
        source_name="Yahoo Finance (reported statements)",
        source_url=f"https://finance.yahoo.com/quote/{ticker}/financials",
        citation=f"Reported financial statements for {ticker}, latest period {financials.get('latest_period')}",
        content=financials,
        summary=(
            f"Revenue {_fmt_money(financials.get('revenue'))}, "
            f"net income {_fmt_money(financials.get('net_income'))}"
        ),
        retrieved_at=datetime.now(timezone.utc),
        confidence=confidence,
    )


def handle_statements(inputs: dict, run_id: str, task_id: str) -> tuple[list[Evidence], float, str | None, list[Claim]]:
    ticker = (inputs or {}).get("ticker")
    if not ticker:
        raise ValueError("financials.statements requires a 'ticker' input")

    financials = get_financials(ticker)
    confidence, degraded = _data_quality(financials)
    evidence = _statements_evidence(run_id, task_id, ticker, financials, confidence)
    return [evidence], confidence, degraded, []


def handle_ratios(inputs: dict, run_id: str, task_id: str) -> tuple[list[Evidence], float, str | None, list[Claim]]:
    """
    Compute metrics deterministically, then have the LLM interpret them.

    Returns evidence plus a Claim carrying the interpretation. The claim
    cites the metrics evidence, so the narrative is anchored to the numbers
    it describes rather than floating free.
    """
    ticker = (inputs or {}).get("ticker")
    company_name = (inputs or {}).get("company_name") or ticker
    if not ticker:
        raise ValueError("financials.ratios requires a 'ticker' input")

    profile = (inputs or {}).get("industry_profile") or {}
    required_metrics = (
        (inputs or {}).get("required_metrics")
        or profile.get("required_financial_metrics")
    )

    financials = get_financials(ticker)
    metrics = compute_metrics(financials, required_metrics)
    confidence, degraded = _data_quality(financials)

    meaningful = sum(1 for m in metrics.values() if m["meaningful"])
    content = {
        "ticker": ticker,
        "profile_id": profile.get("profile_id") or (inputs or {}).get("profile_id"),
        "industry_profile": profile.get("display_name"),
        "required_metrics": required_metrics,
        "metrics": metrics,
        "meaningful_count": meaningful,
        "total_count": len(metrics),
        "latest_period": financials.get("latest_period"),
        "currency": financials.get("currency"),
    }

    evidence = Evidence(
        evidence_id=Evidence.make_id(AGENT_ID, Capability.FINANCIAL_RATIOS, content, run_id),
        run_id=run_id, task_id=task_id, agent_id=AGENT_ID,
        capability=Capability.FINANCIAL_RATIOS,
        source_type=SourceType.COMPUTED,
        source_name="Deterministic ratio calculation",
        citation=(
            f"Ratios computed from {ticker} reported statements "
            f"(period {financials.get('latest_period')})"
        ),
        content=content,
        summary=f"{meaningful}/{len(metrics)} metrics computable",
        retrieved_at=datetime.now(timezone.utc),
        confidence=confidence,
    )

    claims: list[Claim] = []
    if interpretation := _interpret(company_name, ticker, metrics, profile):
        claims.append(
            Claim(
                claim_id=f"claim_{evidence.evidence_id[3:]}_interp",
                run_id=run_id,
                text=interpretation,
                evidence_ids=[evidence.evidence_id],  # anchored to the numbers
                confidence=confidence,
                polarity=Polarity.NEUTRAL,
                category="financial",
                author_agent_id=AGENT_ID,
                created_at=datetime.now(timezone.utc),
            )
        )

    return [evidence], confidence, degraded, claims
