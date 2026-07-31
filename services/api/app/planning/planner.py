"""
Research Planner Agent.

Turns a confirmed company into an executable `ResearchPlan`: which
specialists to run, in what dependency order, using which metrics and
valuation methods.

Two design decisions worth stating plainly:

1. The plan is DATA, not control flow. It is logged, diffed across
   revisions, rendered in the UI, and asserted against in tests. That is
   what makes the planning "explicit and inspectable" rather than a
   pipeline with a planning-shaped comment on it.

2. Playbook selection is DETERMINISTIC; the LLM refines and explains it.
   The industry framework a bank or REIT requires is settled knowledge, not
   something worth re-deriving probabilistically on every run. The LLM adds
   company-specific rationale and can override the classification when it
   has a defensible reason -- but the system produces a competent plan with
   no LLM at all, which is why it stays demonstrable without an API key.
"""

import json
import logging
import uuid
from datetime import datetime, timezone

from contracts import Criticality, IndustryPlaybook, ResearchPlan, TaskSpec

from ..config import get_settings
from . import playbooks

log = logging.getLogger(__name__)

# Capabilities that must run before dependent analysis can start. Valuation
# needs statements; competitor analysis needs to know what the company does.
_DEPENDENCIES: dict[str, list[str]] = {
    "financials.ratios": ["financials.statements"],
    "valuation.estimate": ["financials.statements", "financials.ratios"],
    "competitors.analysis": ["company.profile"],
    "risk.analysis": ["company.profile", "financials.statements"],
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
    """
    Ask the LLM to confirm or override the deterministic classification.

    Any failure returns the deterministic choice unchanged: a planner that
    cannot plan without a working LLM would make the whole platform as
    reliable as its flakiest dependency.
    """
    settings = get_settings()
    if not settings.openai_api_key:
        return default, (
            f"{playbooks.get_playbook(default).rationale} "
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
                    options=", ".join(p.value for p in IndustryPlaybook),
                ),
            }],
        )
        payload = json.loads(response.choices[0].message.content or "{}")
    except Exception as e:  # noqa: BLE001
        log.warning("planner LLM refinement unavailable, using deterministic plan: %s", e)
        return default, (
            f"{playbooks.get_playbook(default).rationale} "
            f"(Selected deterministically: {default_reason}.)"
        )

    try:
        chosen = IndustryPlaybook(payload.get("classification", default.value))
    except ValueError:
        chosen = default

    rationale = payload.get("rationale") or playbooks.get_playbook(chosen).rationale
    if chosen != default:
        rationale = f"{rationale} (Overrode deterministic choice of '{default.value}'.)"
    return chosen, rationale


def _build_tasks(playbook: playbooks.Playbook, ticker: str, company_name: str) -> list[TaskSpec]:
    """
    Expand a playbook's capabilities into a dependency-ordered task DAG.

    Dependencies come from `_DEPENDENCIES` and are filtered to capabilities
    actually present in this plan -- so a playbook that omits
    `financials.ratios` doesn't leave `valuation.estimate` waiting forever on
    a task that was never scheduled.
    """
    selected = playbook.required_capabilities + playbook.optional_capabilities
    present = set(selected)
    inputs = {"ticker": ticker, "company_name": company_name}

    tasks: list[TaskSpec] = []
    for capability in selected:
        required = capability in playbook.required_capabilities
        depends = [d for d in _DEPENDENCIES.get(capability, []) if d in present]

        tasks.append(
            TaskSpec(
                task_id=f"task_{capability.replace('.', '_')}",
                capability=capability,
                inputs=dict(inputs),
                # Dependencies are declared by capability; task_ids follow the
                # same derivation, so this stays consistent.
                depends_on=[f"task_{d.replace('.', '_')}" for d in depends],
                criticality=Criticality.REQUIRED if required else Criticality.OPTIONAL,
                timeout_s=90,
                max_retries=get_settings().max_task_retries,
                rationale=(
                    f"{'Required' if required else 'Optional'} for "
                    f"{playbook.display_name} analysis."
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
    """
    Produce a validated ResearchPlan.

    `ResearchPlan` self-validates its DAG on construction, so a malformed
    plan raises here rather than hanging the Director mid-execution.
    """
    default, reason = playbooks.classify(sector, industry)
    classification, rationale = _llm_refine(
        company_name, ticker, sector, industry, default, reason
    )
    playbook = playbooks.get_playbook(classification)

    tasks = _build_tasks(playbook, ticker, company_name)

    # A replan (HITL #2 requested more analysis) can add capabilities the
    # original plan omitted.
    if extra_capabilities:
        existing = {t.capability for t in tasks}
        for capability in extra_capabilities:
            if capability in existing:
                continue
            tasks.append(
                TaskSpec(
                    task_id=f"task_{capability.replace('.', '_')}",
                    capability=capability,
                    inputs={"ticker": ticker, "company_name": company_name},
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
        valuation_methods=playbook.valuation_methods,
        required_metrics=playbook.required_metrics,
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
    """
    LangGraph node: build the research plan for a confirmed company.

    Serializes the plan into state so the Director, the UI, and LangSmith
    traces all read the same artifact.
    """
    run_id = state["run_id"]
    revision = state.get("plan_revision", 0)

    try:
        plan = build_plan(
            run_id=run_id,
            ticker=state["ticker"],
            company_name=state.get("company_name") or state["ticker"],
            sector=state.get("sector"),
            industry=state.get("industry"),
            revision=revision,
            parent_revision=revision - 1 if revision > 0 else None,
            replan_reason=state.get("committee_feedback") if revision > 0 else None,
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

    return {
        "plan": plan.model_dump(mode="json"),
        "classification": plan.classification.value,
        "status": "planned",
    }
