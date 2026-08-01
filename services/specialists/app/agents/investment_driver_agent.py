"""
Investment Driver Agent.

Evaluates the industry-specific investment drivers and KPIs defined in the
selected profile against computed financial evidence. Drivers are assessed
deterministically from metrics; the LLM only summarizes when available.
"""

import logging
from datetime import datetime, timezone

from contracts import Capability, Claim, Evidence, Polarity, SourceType

from ..config import get_settings
from ..tools.financial_calculations import compute_metrics
from ..tools.yfinance_tool import get_financials

log = logging.getLogger(__name__)

AGENT_ID = "investment_driver_agent"

# Map KPI names to underlying computed metrics for directional assessment
_KPI_METRIC_MAP: dict[str, str] = {
    "revenue_growth": "revenue_growth",
    "gross_margin": "gross_margin",
    "rule_of_40": "rule_of_40",
    "rd_to_revenue": "rd_to_revenue",
    "net_interest_margin": "net_interest_margin",
    "return_on_equity": "return_on_equity",
    "efficiency_ratio": "efficiency_ratio",
    "combined_ratio": "combined_ratio",
    "cash_runway_months": "cash_runway_months",
    "free_cash_flow": "free_cash_flow",
    "operating_margin": "operating_margin",
    "same_store_sales_growth": "same_store_sales_growth",
    "inventory_turnover": "inventory_turnover",
    "return_on_invested_capital": "return_on_invested_capital",
    "backlog_growth": "backlog_growth",
    "dividend_yield": "dividend_yield",
    "debt_to_ebitda": "debt_to_ebitda",
}

_POSITIVE_THRESHOLDS: dict[str, tuple[str, float]] = {
    "revenue_growth": ("gt", 0.05),
    "gross_margin": ("gt", 0.40),
    "rule_of_40": ("gt", 40),
    "return_on_equity": ("gt", 0.12),
    "operating_margin": ("gt", 0.15),
    "free_cash_flow": ("gt", 0),
}

_SUMMARY_PROMPT = """You are an investment analyst summarizing industry-specific drivers for a {industry_label} company.

Business model: {business_model}

Driver assessments (based on computed metrics — do not invent figures):
{assessments}

Investment drivers to monitor for this industry:
{drivers}

Write 4-5 sentences on which drivers appear supported or challenged by the data.
No buy/sell recommendation."""


def _assess_kpi(kpi: str, metrics: dict) -> dict:
    metric_key = _KPI_METRIC_MAP.get(kpi, kpi)
    m = metrics.get(metric_key, {})
    if not m.get("meaningful"):
        return {
            "kpi": kpi,
            "status": "insufficient_data",
            "detail": m.get("flag") or f"{metric_key} not computable from available data",
            "polarity": Polarity.NEUTRAL.value,
        }

    value = m.get("value")
    threshold = _POSITIVE_THRESHOLDS.get(metric_key)
    if threshold:
        op, cut = threshold
        positive = (value > cut) if op == "gt" else (value < cut)
        return {
            "kpi": kpi,
            "status": "supportive" if positive else "challenged",
            "detail": f"{metric_key} = {m['formatted']}",
            "polarity": Polarity.BULL.value if positive else Polarity.BEAR.value,
        }

    return {
        "kpi": kpi,
        "status": "observed",
        "detail": f"{metric_key} = {m['formatted']}",
        "polarity": Polarity.NEUTRAL.value,
    }


def _summarize(
    assessments: list[dict], drivers: list[str], profile: dict,
) -> str | None:
    settings = get_settings()
    if not settings.openai_api_key:
        return None

    text = "\n".join(
        f"- {a['kpi']}: {a['status']} ({a['detail']})" for a in assessments
    )
    try:
        from openai import OpenAI

        client = OpenAI(api_key=settings.openai_api_key)
        response = client.chat.completions.create(
            model=settings.model_interpretation,
            temperature=settings.temperature,
            max_tokens=400,
            messages=[{
                "role": "user",
                "content": _SUMMARY_PROMPT.format(
                    industry_label=profile.get("display_name", "general"),
                    business_model=profile.get("business_model", ""),
                    assessments=text,
                    drivers="\n".join(f"- {d}" for d in drivers),
                ),
            }],
        )
        return (response.choices[0].message.content or "").strip() or None
    except Exception as e:  # noqa: BLE001
        log.warning("investment driver summary unavailable: %s", e)
        return None


def handle(inputs: dict, run_id: str, task_id: str) -> tuple[list[Evidence], float, str | None, list[Claim]]:
    ticker = (inputs or {}).get("ticker")
    if not ticker:
        raise ValueError("investment.drivers requires a 'ticker' input")

    profile = (inputs or {}).get("industry_profile") or {}
    drivers = (inputs or {}).get("investment_drivers") or profile.get("investment_drivers") or []
    kpis = (inputs or {}).get("key_performance_indicators") or profile.get("key_performance_indicators") or []
    metric_names = profile.get("required_financial_metrics")

    financials = get_financials(ticker)
    metrics = compute_metrics(financials, metric_names)

    kpi_assessments = [_assess_kpi(kpi, metrics) for kpi in kpis]
    driver_links = [
        {"driver": d, "related_kpis": kpis[:3]} for d in drivers
    ]

    supportive = sum(1 for a in kpi_assessments if a["status"] == "supportive")
    challenged = sum(1 for a in kpi_assessments if a["status"] == "challenged")
    summary = _summarize(kpi_assessments, drivers, profile)

    content = {
        "ticker": ticker,
        "profile_id": profile.get("profile_id") or (inputs or {}).get("profile_id"),
        "investment_drivers": drivers,
        "kpi_assessments": kpi_assessments,
        "driver_links": driver_links,
        "supportive_count": supportive,
        "challenged_count": challenged,
        "summary": summary,
    }

    meaningful = sum(1 for a in kpi_assessments if a["status"] != "insufficient_data")
    confidence = round(min(0.85, 0.35 + 0.1 * meaningful), 2)
    degraded = "many KPIs require supplemental industry data" if meaningful < len(kpis) / 2 else None

    evidence = Evidence(
        evidence_id=Evidence.make_id(AGENT_ID, Capability.INVESTMENT_DRIVERS, content, run_id),
        run_id=run_id, task_id=task_id, agent_id=AGENT_ID,
        capability=Capability.INVESTMENT_DRIVERS,
        source_type=SourceType.COMPUTED,
        source_name="Industry profile investment driver assessment",
        citation=f"Investment drivers for {ticker} using {profile.get('display_name', 'general')} profile",
        content=content,
        summary=f"{supportive} supportive / {challenged} challenged KPIs across {len(drivers)} drivers",
        retrieved_at=datetime.now(timezone.utc),
        confidence=confidence,
        provider_degraded=degraded is not None,
    )

    claims: list[Claim] = []
    if summary:
        polarity = (
            Polarity.BULL if supportive > challenged
            else Polarity.BEAR if challenged > supportive
            else Polarity.NEUTRAL
        )
        claims.append(
            Claim(
                claim_id=f"claim_{evidence.evidence_id[3:]}_drivers",
                run_id=run_id,
                text=summary,
                evidence_ids=[evidence.evidence_id],
                confidence=confidence,
                polarity=polarity,
                category="investment_drivers",
                author_agent_id=AGENT_ID,
                created_at=datetime.now(timezone.utc),
            )
        )

    return [evidence], confidence, degraded, claims
