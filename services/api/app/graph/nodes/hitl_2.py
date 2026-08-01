"""
HITL Checkpoint #2 — Investment Committee Review.

The human sees the gated recommendation and can approve, reject, or request
additional analysis. A replan request loops back to the Planner, which
produces a new plan revision; the Director dispatches only the delta.
"""

import logging

from contracts import HumanDecision, TaskState
from langgraph.types import interrupt

from ...committee.brief_builder import parse_replan_capabilities
from ...config import get_settings
from ...evidence import repository as evidence_repo
from ...report.repository import get_report, mark_report_approved
from ...thesis import repository as thesis_repo
from ...thesis.framework import build_structured_thesis

log = logging.getLogger(__name__)


async def _review_summary(state: dict) -> dict:
    """Plain-language research summary for the human reviewer."""
    run_id = state["run_id"]
    thesis = await thesis_repo.get_latest_version(run_id)
    report = await get_report(run_id)

    research_summary = None
    if report:
        for section in report.sections:
            if section.section_id == "executive_summary":
                research_summary = section.body
                break

    recommendation = state.get("recommendation") or {}
    if not research_summary:
        research_summary = recommendation.get("cio_rationale")

    framework = state.get("thesis_framework")
    if framework is None and thesis:
        evidence_records = await evidence_repo.get_evidence_for_run(run_id)
        built = build_structured_thesis(
            company=state.get("company_name") or state.get("ticker") or "",
            ticker=state.get("ticker") or "",
            evidence_records=evidence_records,
            state=state,
            recommendation=recommendation,
            safety_report=state.get("safety_report"),
        )
        framework = built.model_dump(mode="json")

    safety = state.get("safety_report") or {}
    coverage = safety.get("coverage") or {}
    required = coverage.get("required_capabilities") or []
    satisfied = coverage.get("satisfied_capabilities") or []
    coverage_ratio = coverage.get("coverage_ratio")
    if coverage_ratio is None and required:
        coverage_ratio = len(satisfied) / max(1, len(required))

    thesis_statement = None
    if framework:
        thesis_statement = framework.get("primary_thesis")
    elif thesis:
        thesis_statement = thesis.statement

    return {
        "research_summary": research_summary,
        "thesis_statement": thesis_statement,
        "thesis_framework": framework,
        "thesis_stance": state.get("thesis_stance") or (thesis.stance.value if thesis else None),
        "thesis_confidence": state.get("thesis_confidence") or (thesis.confidence if thesis else None),
        "evidence_score": recommendation.get("evidence_score") or safety.get("evidence_score"),
        "coverage_ratio": coverage_ratio,
        "failed_capabilities": coverage.get("failed_capabilities") or [],
    }


async def hitl_2_node(state: dict) -> dict:
    """Pause for human review of the committee recommendation."""
    recommendation = state.get("recommendation") or {}
    summary = await _review_summary(state)

    decision = interrupt(
        {
            "type": "checkpoint_2_committee_review",
            "run_id": state["run_id"],
            "ticker": state.get("ticker"),
            "company_name": state.get("company_name"),
            "recommendation": {
                "action": recommendation.get("action"),
                "confidence": recommendation.get("confidence"),
                "evidence_score": recommendation.get("evidence_score"),
                "was_downgraded": recommendation.get("was_downgraded"),
                "gate_reasons": recommendation.get("gate_reasons"),
            },
            "bull_case": recommendation.get("bull_case"),
            "bear_case": recommendation.get("bear_case"),
            "cio_rationale": recommendation.get("cio_rationale"),
            "research_summary": summary.get("research_summary"),
            "thesis_statement": summary.get("thesis_statement"),
            "thesis_framework": summary.get("thesis_framework"),
            "thesis_stance": summary.get("thesis_stance"),
            "thesis_confidence": summary.get("thesis_confidence"),
            "evidence_score": summary.get("evidence_score"),
            "coverage_ratio": summary.get("coverage_ratio"),
            "failed_capabilities": summary.get("failed_capabilities"),
            "report_id": state.get("report_id"),
            "prompt": (
                f"Review the investment research report and committee recommendation for "
                f"{state.get('company_name')} ({state.get('ticker')})."
            ),
            "options": ["approve", "reject", "request_analysis"],
        }
    )

    result = _apply_checkpoint_2_decision(decision, state)

    if result.get("committee_decision") == HumanDecision.APPROVE.value:
        await mark_report_approved(state["run_id"])

    return result


def _apply_checkpoint_2_decision(decision, state: dict) -> dict:
    """Interpret the human's Checkpoint #2 response."""
    action = decision
    feedback = None

    if isinstance(decision, dict):
        action = decision.get("action", "approve")
        feedback = decision.get("feedback")

    action_normalized = str(action).strip().lower()

    if action_normalized in {"approve", "yes", "y", "true"}:
        return {
            "committee_decision": HumanDecision.APPROVE.value,
            "status": "complete",
        }

    if action_normalized in {"reject", "no", "n", "false"}:
        return {
            "committee_decision": HumanDecision.REJECT.value,
            "status": "rejected",
        }

    if action_normalized in {"request_analysis", "replan", "more", "request"}:
        settings = get_settings()
        replan_rounds = state.get("replan_rounds", 0)

        if replan_rounds >= settings.max_replan_rounds:
            log.warning(
                "run %s replan limit reached (%d); treating as reject",
                state["run_id"], settings.max_replan_rounds,
            )
            return {
                "committee_decision": HumanDecision.REJECT.value,
                "committee_feedback": feedback,
                "status": "replan_limit_reached",
            }

        # Clear task statuses for failed tasks and feedback-requested capabilities
        # so the Director re-dispatches only the delta.
        task_status = dict(state.get("task_status") or {})
        requested_caps = parse_replan_capabilities(feedback)

        cleared: list[str] = []
        for task_id, info in list(task_status.items()):
            should_clear = (
                info.get("state") == TaskState.FAILED.value
                or info.get("capability") in requested_caps
            )
            if should_clear:
                del task_status[task_id]
                cleared.append(task_id)

        log.info(
            "run %s replan requested (round %d): cleared %d task(s), feedback=%r",
            state["run_id"], replan_rounds + 1, len(cleared), feedback,
        )

        return {
            "committee_decision": HumanDecision.REQUEST_ANALYSIS.value,
            "committee_feedback": feedback,
            "replan_rounds": replan_rounds + 1,
            "plan_revision": state.get("plan_revision", 0) + 1,
            "task_status": task_status,
            "recommendation": None,
            "committee_proposal": None,
            "safety_report": None,
            "evidence_score": None,
            "report_id": None,
            "status": "replanning",
        }

    # Unrecognized action defaults to approve to avoid trapping the workflow.
    log.warning("unrecognized HITL #2 action %r; defaulting to approve", action)
    return {
        "committee_decision": HumanDecision.APPROVE.value,
        "status": "complete",
    }


def route_after_hitl_2(state: dict) -> str:
    """Route after human committee review."""
    status = state.get("status", "")
    if status == "replanning":
        return "replan"
    return "complete"
