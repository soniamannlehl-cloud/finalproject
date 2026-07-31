"""
Risk Analysis Agent.

Identifies risks from measurable financial signals rather than from generic
industry boilerplate. "Elevated leverage: debt/EBITDA of 5.8x" is a finding;
"the company faces competitive pressures" is filler that would be true of
every company ever analyzed.

Detection is deterministic and threshold-based, so each flagged risk is
reproducible and traceable to the number that triggered it. The LLM, when
available, only writes the narrative around already-detected risks -- it
cannot invent a risk that no signal supports.
"""

import logging
from datetime import datetime, timezone

from contracts import Capability, Claim, Evidence, Polarity, SourceType

from ..config import get_settings
from ..tools.financial_calculations import compute_all
from ..tools.yfinance_tool import get_financials

log = logging.getLogger(__name__)

AGENT_ID = "risk_analyst_agent"

# Thresholds chosen to flag genuinely notable conditions rather than fire on
# every company. Each carries the reason it matters, so the report can
# explain the flag rather than just asserting it.
_RISK_RULES = [
    {
        "id": "high_leverage",
        "metric": "debt_to_ebitda",
        "test": lambda v: v is not None and v > 4.0,
        "severity": "high",
        "title": "Elevated financial leverage",
        "why": "Debt above 4x EBITDA limits flexibility and raises refinancing sensitivity to rates.",
    },
    {
        "id": "negative_fcf",
        "metric": "free_cash_flow",
        "test": lambda v: v is not None and v < 0,
        "severity": "high",
        "title": "Negative free cash flow",
        "why": "The business consumes more cash than it generates, implying reliance on external funding.",
    },
    {
        "id": "thin_liquidity",
        "metric": "current_ratio",
        "test": lambda v: v is not None and v < 1.0,
        "severity": "medium",
        "title": "Current liabilities exceed current assets",
        "why": "Short-term obligations are not covered by short-term assets.",
    },
    {
        "id": "revenue_decline",
        "metric": "revenue_growth",
        "test": lambda v: v is not None and v < -0.05,
        "severity": "medium",
        "title": "Declining revenue",
        "why": "Revenue contracted year over year, which pressures operating leverage.",
    },
    {
        "id": "margin_pressure",
        "metric": "operating_margin",
        "test": lambda v: v is not None and v < 0,
        "severity": "high",
        "title": "Operating losses",
        "why": "Core operations are unprofitable before financing and tax effects.",
    },
    {
        "id": "rich_valuation",
        "metric": "pe_ratio",
        "test": lambda v: v is not None and v > 50,
        "severity": "medium",
        "title": "Demanding valuation multiple",
        "why": "A P/E above 50x prices in substantial growth; shortfalls tend to de-rate sharply.",
    },
]

_NARRATIVE_PROMPT = """You are a risk analyst. These risks were detected from measured financial data:

{risks}

Industry context: {industry_risks}

Write 3-4 sentences summarizing this company's risk profile.
Rules:
- Discuss ONLY the detected risks listed above; do not introduce new ones.
- If no financial risks were detected, say the measured indicators appear sound and note
  that industry-level risks still apply.
- No investment advice."""


def _narrative(detected: list[dict], industry_risks: list[str]) -> str | None:
    settings = get_settings()
    if not settings.openai_api_key:
        return None

    risk_text = (
        "\n".join(f"- {r['title']}: {r['detail']} ({r['why']})" for r in detected)
        or "- No threshold-based financial risks detected."
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
                "content": _NARRATIVE_PROMPT.format(
                    risks=risk_text,
                    industry_risks=", ".join(industry_risks) or "none supplied",
                ),
            }],
        )
        return (response.choices[0].message.content or "").strip() or None
    except Exception as e:  # noqa: BLE001
        log.warning("risk narrative unavailable: %s", e)
        return None


def handle(inputs: dict, run_id: str, task_id: str) -> tuple[list[Evidence], float, str | None, list[Claim]]:
    ticker = (inputs or {}).get("ticker")
    if not ticker:
        raise ValueError("risk.analysis requires a 'ticker' input")

    industry_risks = (inputs or {}).get("industry_risks") or []

    financials = get_financials(ticker)
    metrics = compute_all(financials)

    detected = []
    for rule in _RISK_RULES:
        metric = metrics.get(rule["metric"], {})
        if not metric.get("meaningful"):
            continue  # can't flag a risk from a number we don't have
        if rule["test"](metric.get("value")):
            detected.append({
                "id": rule["id"],
                "title": rule["title"],
                "severity": rule["severity"],
                "metric": rule["metric"],
                "value": metric["value"],
                "detail": f"{rule['metric']} = {metric['formatted']}",
                "why": rule["why"],
            })

    high = sum(1 for r in detected if r["severity"] == "high")
    narrative = _narrative(detected, industry_risks)

    content = {
        "ticker": ticker,
        "detected_risks": detected,
        "risk_count": len(detected),
        "high_severity_count": high,
        "industry_risks": industry_risks,
        "narrative": narrative,
        "metrics_evaluated": sum(1 for m in metrics.values() if m["meaningful"]),
        "detection_method": "deterministic threshold rules over computed financial metrics",
    }

    # Confidence measures how well we could ASSESS risk, not how risky the
    # company is: more computable metrics means a more complete assessment.
    evaluable = content["metrics_evaluated"]
    confidence = round(min(0.9, 0.4 + 0.04 * evaluable), 2)
    degraded = "limited financial data reduced risk-detection coverage" if evaluable < 8 else None

    evidence = Evidence(
        evidence_id=Evidence.make_id(AGENT_ID, Capability.RISK_ANALYSIS, content),
        run_id=run_id, task_id=task_id, agent_id=AGENT_ID,
        capability=Capability.RISK_ANALYSIS,
        source_type=SourceType.COMPUTED,
        source_name="Threshold-based risk detection",
        citation=(
            f"Risk assessment for {ticker} across {evaluable} computed metric(s); "
            f"{len(detected)} risk(s) flagged"
        ),
        content=content,
        summary=f"{len(detected)} risk(s) detected ({high} high severity)",
        retrieved_at=datetime.now(timezone.utc),
        confidence=confidence,
        provider_degraded=degraded is not None,
    )

    claims: list[Claim] = []
    if narrative:
        claims.append(
            Claim(
                claim_id=f"claim_{evidence.evidence_id[3:]}_risk",
                run_id=run_id,
                text=narrative,
                evidence_ids=[evidence.evidence_id],
                confidence=confidence,
                polarity=Polarity.BEAR if detected else Polarity.NEUTRAL,
                category="risk",
                author_agent_id=AGENT_ID,
                created_at=datetime.now(timezone.utc),
            )
        )

    return [evidence], confidence, degraded, claims
