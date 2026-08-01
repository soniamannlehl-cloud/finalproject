"""
Assemble an InvestmentReport from workflow state and persisted artifacts.
"""

import logging
import uuid
from datetime import datetime, timezone

from contracts import (
    Evidence,
    InvestmentReport,
    Polarity,
    Recommendation,
    ReportSection,
    SourceType,
    TaskState,
    ThesisVersion,
)

from ..config import get_settings
from ..evidence import repository as evidence_repo
from ..thesis import repository as thesis_repo
from ..thesis.framework import build_structured_thesis
from . import formatters as fmt

log = logging.getLogger(__name__)

_SECTION_ORDER = [
    ("executive_summary", "Executive Summary", 1),
    ("investment_thesis", "Investment Thesis", 2),
    ("investment_drivers", "Investment Drivers", 3),
    ("business_overview", "Business Overview", 4),
    ("industry_analysis", "Industry Analysis", 5),
    ("financial_analysis", "Financial Analysis", 6),
    ("valuation", "Valuation", 7),
    ("competitive_analysis", "Competitive Analysis", 8),
    ("news_summary", "News Summary", 9),
    ("sec_filings", "SEC Filing Summary", 10),
    ("earnings", "Earnings Call Summary", 11),
    ("risk_analysis", "Risk Analysis", 12),
    ("limitations", "Limitations", 13),
    ("sources", "Sources", 14),
]


def _executive_summary(
    company: str, ticker: str, recommendation: Recommendation, thesis: ThesisVersion | None
) -> str:
    settings = get_settings()
    action = recommendation.action.value.replace("_", " ").title()
    base = (
        f"This report covers {company} ({ticker}). "
        f"The investment committee recommendation is <strong>{action}</strong> "
        f"with {recommendation.confidence:.0%} confidence "
        f"and an evidence score of {recommendation.evidence_score:.2f}."
    )
    if recommendation.was_downgraded:
        base += (
            f" Note: the recommendation was downgraded by the safety gate "
            f"({'; '.join(recommendation.gate_reasons[:2])})."
        )

    if not settings.openai_api_key:
        if thesis:
            base += f" Current thesis stance: {thesis.stance.value} ({thesis.confidence:.0%} confidence)."
        return f"<p>{base}</p>"

    try:
        from openai import OpenAI

        client = OpenAI(api_key=settings.openai_api_key)
        response = client.chat.completions.create(
            model=settings.resolve_model("report_prose"),
            temperature=0.0,
            max_tokens=400,
            messages=[{
                "role": "user",
                "content": (
                    f"Write a 4-6 sentence executive summary for an investment research report on "
                    f"{company} ({ticker}). Recommendation: {action}. "
                    f"CIO rationale: {fmt.clean_prose(recommendation.cio_rationale)[:600]}. "
                    f"Do not invent facts beyond what is stated."
                ),
            }],
        )
        prose = (response.choices[0].message.content or "").strip()
        return f"<p>{prose}</p>" if prose else f"<p>{base}</p>"
    except Exception as e:  # noqa: BLE001
        log.warning("executive summary LLM unavailable: %s", e)
        return f"<p>{base}</p>"


def _declared_gaps(state: dict) -> list[str]:
    gaps = []
    for task_id, info in (state.get("task_status") or {}).items():
        if info.get("declared_gap") or info.get("state") == TaskState.SKIPPED.value:
            cap = info.get("capability", task_id)
            reason = info.get("error") or info.get("degraded_reason") or "not completed"
            gaps.append(f"{cap}: {reason}")
    return gaps


def _limitations(state: dict, safety_report: dict | None) -> list[str]:
    limits = [
        "This is an academic research simulation, not investment advice.",
        "Analysis relies on publicly available data and may be incomplete.",
    ]
    if safety_report:
        not_run = [
            f["message"] for f in safety_report.get("findings", [])
            if str(f.get("check_name", "")).endswith("_not_run")
        ]
        limits.extend(not_run[:3])
    if state.get("committee_decision") == "reject":
        limits.append("Human reviewer rejected the committee recommendation.")
    return limits


async def build_report(state: dict, approved: bool = True) -> InvestmentReport:
    """Construct a complete InvestmentReport from run state."""
    run_id = state["run_id"]
    recommendation = Recommendation.model_validate(state["recommendation"])

    thesis = await thesis_repo.get_latest_version(run_id)
    if thesis is None:
        thesis = ThesisVersion(
            run_id=run_id, version=1, statement="No thesis formed.",
            stance=Polarity.NEUTRAL,
            confidence=0.0, change_reason="none", triggered_by="report",
            created_at=datetime.now(timezone.utc),
        )

    evidence_records = await evidence_repo.get_evidence_for_run(run_id)
    claims_raw = await evidence_repo.get_claims_for_run(run_id)

    framework = build_structured_thesis(
        company=state.get("company_name") or state.get("ticker") or "",
        ticker=state.get("ticker") or "",
        evidence_records=evidence_records,
        state=state,
        recommendation=state.get("recommendation"),
        safety_report=state.get("safety_report"),
    )
    if thesis.framework is None:
        thesis = thesis.model_copy(update={"framework": framework})

    by_cap: dict[str, list[dict]] = {}
    for r in evidence_records:
        by_cap.setdefault(r["capability"], []).append(r)

    cap_sections = {
        "business_overview": by_cap.get("company.profile", []),
        "financial_analysis": by_cap.get("financials.ratios", []) + by_cap.get("financials.statements", []),
        "valuation": by_cap.get("valuation.estimate", []),
        "competitive_analysis": by_cap.get("competitors.analysis", []),
        "news_summary": by_cap.get("news.sentiment", []),
        "sec_filings": by_cap.get("filings.sec", []),
        "earnings": by_cap.get("earnings.call", []),
        "risk_analysis": by_cap.get("risk.analysis", []),
        "investment_drivers": by_cap.get("investment.drivers", []),
    }

    sections: list[ReportSection] = []
    sections.append(ReportSection(
        section_id="executive_summary", title="Executive Summary", order=1,
        body=_executive_summary(
            state.get("company_name") or state.get("ticker", ""),
            state.get("ticker", ""),
            recommendation,
            thesis,
        ),
        claim_ids=[],
    ))

    order = 2
    for sid, title, _ in _SECTION_ORDER[1:]:
        body = ""
        if sid == "industry_analysis":
            body = fmt.format_industry_analysis(
                state.get("industry"),
                state.get("classification"),
                cap_sections["business_overview"],
                cap_sections["competitive_analysis"],
            )
        elif sid == "business_overview":
            body = fmt.format_business_overview(cap_sections["business_overview"])
        elif sid == "financial_analysis":
            body = fmt.format_financial_analysis(cap_sections["financial_analysis"], claims_raw)
        elif sid == "valuation":
            body = fmt.format_valuation(cap_sections["valuation"])
        elif sid == "competitive_analysis":
            body = fmt.format_competitive_analysis(cap_sections["competitive_analysis"])
        elif sid == "news_summary":
            body = fmt.format_news(cap_sections["news_summary"], claims_raw)
        elif sid == "earnings":
            body = fmt.format_earnings(cap_sections["earnings"])
        elif sid == "sec_filings":
            body = fmt.format_evidence_section(cap_sections["sec_filings"], claims_raw, "No SEC filing data gathered.")
        elif sid == "risk_analysis":
            body = fmt.format_evidence_section(cap_sections["risk_analysis"], claims_raw, "No dedicated risk analysis was run.")
        elif sid == "investment_thesis":
            body = fmt.format_investment_thesis(framework)
        elif sid == "investment_drivers":
            body = fmt.format_investment_drivers(cap_sections["investment_drivers"], state.get("industry_profile"))
        elif sid == "limitations":
            body = "<ul>" + "".join(f"<li>{l}</li>" for l in _limitations(state, state.get("safety_report"))) + "</ul>"
        elif sid == "sources":
            rows = []
            for e in evidence_records[:25]:
                url = e.get("source_url") or ""
                cite = e.get("citation") or e.get("source_name") or "Source"
                cap = e.get("capability", "").replace(".", " · ")
                link = f'<a href="{url}">{url}</a>' if url else "—"
                rows.append([cap, cite, link])
            body = fmt._table(["Capability", "Citation", "URL"], rows) if rows else "<p>No sources recorded.</p>"
        else:
            body = "<p>No data available.</p>"

        sections.append(ReportSection(section_id=sid, title=title, order=order, body=body, claim_ids=[]))
        order += 1

    sources: list[Evidence] = []
    for r in evidence_records[:30]:
        try:
            retrieved = r["retrieved_at"]
            if isinstance(retrieved, str):
                retrieved = datetime.fromisoformat(str(retrieved).replace("Z", "+00:00"))
            sources.append(Evidence(
                evidence_id=r["evidence_id"],
                run_id=run_id,
                task_id=r.get("task_id", ""),
                agent_id=r.get("agent_id", ""),
                capability=r["capability"],
                source_type=SourceType(r["source_type"]),
                source_name=r.get("source_name", ""),
                source_url=r.get("source_url"),
                citation=r.get("citation", ""),
                content=r.get("content") or {},
                summary=r.get("summary", ""),
                retrieved_at=retrieved,
                confidence=float(r.get("confidence", 0.0)),
                provider_degraded=bool(r.get("provider_degraded")),
            ))
        except Exception:  # noqa: BLE001
            continue

    now = datetime.now(timezone.utc)
    return InvestmentReport(
        report_id=f"report_{uuid.uuid4().hex[:12]}",
        run_id=run_id,
        ticker=state.get("ticker") or "",
        company_name=state.get("company_name") or state.get("ticker") or "",
        generated_at=now,
        recommendation=recommendation,
        final_thesis=thesis,
        sections=sections,
        sources=sources,
        limitations=_limitations(state, state.get("safety_report")),
        declared_gaps=_declared_gaps(state),
        approved_by_human=approved and state.get("committee_decision") == "approve",
        approved_at=now if approved and state.get("committee_decision") == "approve" else None,
    )
