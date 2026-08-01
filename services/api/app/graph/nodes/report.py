"""LangGraph node: generate and persist the investment report before HITL #2."""

import logging

from ...report.generator import build_report
from ...report.repository import save_report

log = logging.getLogger(__name__)


async def report_generator_node(state: dict) -> dict:
    """Build InvestmentReport for human committee review."""
    run_id = state["run_id"]

    if not state.get("recommendation"):
        log.warning("run %s: report skipped — no recommendation in state", run_id)
        return {
            "status": "report_skipped",
            "errors": [{"stage": "report", "error": "no recommendation"}],
        }

    try:
        report = await build_report(state, approved=False)
        report_id = await save_report(report)
    except Exception as e:  # noqa: BLE001
        log.exception("report generation failed for run %s", run_id)
        return {
            "status": "report_failed",
            "errors": [{"stage": "report", "error": str(e)}],
        }

    log.info("run %s report generated for committee review: %s", run_id, report_id)
    return {
        "report_id": report_id,
        "status": "awaiting_committee_review",
    }
