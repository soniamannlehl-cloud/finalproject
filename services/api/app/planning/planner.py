"""
Research Planner Agent.

Turns a confirmed company into an executable `ResearchPlan`: which
specialists to run, in what dependency order, using which metrics and
valuation methods.

The Planner first selects an industry profile (data-driven configuration),
then builds a task DAG that passes that profile to every downstream agent.
Adding a new industry requires only a new profile — not agent code changes.
"""

import json
import logging
import uuid
from datetime import datetime, timezone

from contracts import Criticality, IndustryPlaybook, ResearchPlan, TaskSpec
from contracts.industry_profiles import classify, get_profile

from ..committee.brief_builder import parse_replan_capabilities
from ..config import get_settings

log = logging.getLogger(__name__)

# Capabilities that must run before dependent analysis can start.
_DEPENDENCIES: dict[str, list[str]] = {
    "financials.ratios": ["financials.statements"],
    "valuation.estimate": ["financials.statements", "financials.ratios"],
    "competitors.analysis": ["company.profile"],
    "risk.analysis": ["company.profile", "financials.statements", "financials.ratios"],
    "investment.drivers": ["company.profile", "financials.ratios"],
}

_CLASSIFY_PROMPT = """You are a senior equity research analyst assigning a company to a research framework.

Company: {company_name} ({ticker})
Reported sector: {sector}
Reported industry: {industry}

A deterministic classifier selected: {default_classification}
Reason: {default_reason}

Available frameworks: {options}

Two questions:
1. Is the selected framework correct for how this company should actually be analyzed?
2. In two sentences, why is this framework right for THIS company specifically?

Respond as JSON only:
{{"classification": "<framework>", "rationale": "<two sentences>", "changed": <true|false>}}"""


def _llm_refine(
    company_name: str, ticker: str, sector: str | None, industry: str | None,
    default: IndustryPlaybook, default_reason: str,
) -> tuple[IndustryPlaybook, str]:
    settings = get_settings()
    profile = get_profile(default)
    if not settings.openai_api_key:
        return default, (
            f"{profile.rationale} "
            f"(Framework selected deterministically: {default_reason}. "
            "No LLM configured, so no company-specific refinement was applied.)"
        )

    try:
        from openai import OpenAI

        client = OpenAI(api_key=settings.openai_api_key)
        response = client.chat.completions.create(
            model=settings.resolve_model("planner"),
            temperature=settings.temperature,
            response_format={"type": "json_object"},
            messages=[{
                "role": "user",
                "content": _CLASSIFY_PROMPT.format(
                    company_name=company_name, ticker=ticker,
                    sector=sector, industry=industry,
                    default_classification=default.value, default_reason=default_reason,
                    options=", ".join(p.value for p in IndustryPlaybook if p != IndustryPlaybook.GENERIC),
                ),
            }],
        )
        payload = json.loads(response.choices[0].message.content or "{}")
    except Exception as e:  # noqa: BLE001
        log.warning("planner LLM refinement unavailable, using deterministic plan: %s", e)
        return default, (
            f"{profile.rationale} (Selected deterministically: {default_reason}.)"
        )

    try:
        chosen = IndustryPlaybook(payload.get("classification", default.value))
    except ValueError:
        chosen = default

    rationale = payload.get("rationale") or get_profile(chosen).rationale
    if chosen != default:
        rationale = f"{rationale} (Overrode deterministic choice of '{default.value}'.)"
    return chosen, rationale


def _profile_inputs(profile, sector: str | None, industry: str | None) -> dict:
    """Shared industry context passed to every industry-aware specialist."""
    payload = profile.task_payload()
    return {
        "industry_profile": payload,
        "profile_id": profile.profile_id.value,
        "sector": sector,
        "industry": industry,
    }


def _build_tasks(
    profile,
    ticker: str,
    company_name: str,
    sector: str | None = None,
    industry: str | None = None,
) -> list[TaskSpec]:
    """Expand a profile's capabilities into a dependency-ordered task DAG."""
    selected = profile.required_capabilities + profile.optional_capabilities
    present = set(selected)
    base_inputs = {"ticker": ticker, "company_name": company_name}
    profile_ctx = _profile_inputs(profile, sector, industry)

    extra_inputs: dict[str, dict] = {
        "financials.ratios": {
            **profile_ctx,
            "required_metrics": profile.required_financial_metrics,
        },
        "valuation.estimate": {
            **profile_ctx,
            "valuation_methods": [v.value for v in profile.valuation_methods],
        },
        "risk.analysis": {
            **profile_ctx,
            "industry_risks": profile.business_risks,
            "risk_rules": [r.model_dump(mode="json") for r in profile.risk_rules],
        },
        "competitors.analysis": {
            **profile_ctx,
            "competitive_factors": profile.competitive_factors,
        },
        "investment.drivers": {
            **profile_ctx,
            "investment_drivers": profile.investment_drivers,
            "key_performance_indicators": profile.key_performance_indicators,
        },
    }

    tasks: list[TaskSpec] = []
    for capability in selected:
        required = capability in profile.required_capabilities
        depends = [d for d in _DEPENDENCIES.get(capability, []) if d in present]

        tasks.append(
            TaskSpec(
                task_id=f"task_{capability.replace('.', '_')}",
                capability=capability,
                inputs={**base_inputs, **extra_inputs.get(capability, profile_ctx)},
                depends_on=[f"task_{d.replace('.', '_')}" for d in depends],
                criticality=Criticality.REQUIRED if required else Criticality.OPTIONAL,
                timeout_s=90,
                max_retries=get_settings().max_task_retries,
                rationale=(
                    f"{'Required' if required else 'Optional'} for "
                    f"{profile.display_name} analysis ({profile.business_model[:60]}…)."
                ),
            )
        )
    return tasks


def build_plan(
    run_id: str, ticker: str, company_name: str,
    sector: str | None, industry: str | None,
    revision: int = 0, parent_revision: int | None = None,
    replan_reason: str | None = None,
    extra_capabilities: list[str] | None = None,
) -> ResearchPlan:
    default, reason = classify(sector, industry)
    classification, rationale = _llm_refine(
        company_name, ticker, sector, industry, default, reason
    )
    profile = get_profile(classification)
    tasks = _build_tasks(profile, ticker, company_name, sector, industry)

    if extra_capabilities:
        existing = {t.capability for t in tasks}
        ctx = _profile_inputs(profile, sector, industry)
        for capability in extra_capabilities:
            if capability in existing:
                continue
            tasks.append(
                TaskSpec(
                    task_id=f"task_{capability.replace('.', '_')}",
                    capability=capability,
                    inputs={"ticker": ticker, "company_name": company_name, **ctx},
                    criticality=Criticality.REQUIRED,
                    max_retries=get_settings().max_task_retries,
                    rationale="Added on replan in response to reviewer feedback.",
                )
            )

    return ResearchPlan(
        plan_id=f"plan_{uuid.uuid4().hex[:10]}",
        run_id=run_id,
        revision=revision,
        parent_revision=parent_revision,
        replan_reason=replan_reason,
        ticker=ticker,
        company_name=company_name,
        classification=classification,
        industry=industry or "unknown",
        sector=sector or "unknown",
        valuation_methods=profile.valuation_methods,
        required_metrics=profile.required_financial_metrics,
        industry_profile=profile.task_payload(),
        tasks=tasks,
        fallback_strategy=(
            "Optional task failures are recorded as declared gaps. Required task "
            "failures reduce the evidence score and, past the policy floor, force "
            "an INSUFFICIENT_EVIDENCE outcome rather than a weakly-supported call."
        ),
        planner_rationale=rationale,
        created_at=datetime.now(timezone.utc),
    )


async def planner_node(state: dict) -> dict:
    """LangGraph node: build the research plan for a confirmed company."""
    run_id = state["run_id"]
    revision = state.get("plan_revision", 0)
    feedback = state.get("committee_feedback") if revision > 0 else None
    extra_caps = parse_replan_capabilities(feedback) if feedback else None

    try:
        plan = build_plan(
            run_id=run_id,
            ticker=state["ticker"],
            company_name=state.get("company_name") or state["ticker"],
            sector=state.get("sector"),
            industry=state.get("industry"),
            revision=revision,
            parent_revision=revision - 1 if revision > 0 else None,
            replan_reason=feedback,
            extra_capabilities=extra_caps,
        )
    except Exception as e:  # noqa: BLE001
        log.exception("planning failed for run %s", run_id)
        return {
            "status": "planning_failed",
            "errors": [{"stage": "planner", "error": str(e)}],
        }

    layers = plan.execution_layers()
    log.info(
        "run %s planned: %s, %d tasks in %d layer(s)",
        run_id, plan.classification.value, len(plan.tasks), len(layers),
    )

    from ..observability.events import log_event
    log_event(run_id, "planner", classification=plan.classification.value, tasks=len(plan.tasks))

    return {
        "plan": plan.model_dump(mode="json"),
        "classification": plan.classification.value,
        "industry_profile": plan.industry_profile,
        "status": "planned",
    }
