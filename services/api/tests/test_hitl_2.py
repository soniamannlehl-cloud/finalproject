"""Tests for HITL #2 routing and replan logic."""

from app.graph.nodes.hitl_2 import route_after_hitl_2, _apply_checkpoint_2_decision
from app.committee.brief_builder import parse_replan_capabilities


class TestParseReplanCapabilities:
    def test_detects_valuation_request(self):
        caps = parse_replan_capabilities("Please do more valuation analysis")
        assert "valuation.estimate" in caps

    def test_detects_multiple_keywords(self):
        caps = parse_replan_capabilities("Need more risk and news sentiment")
        assert "risk.analysis" in caps
        assert "news.sentiment" in caps

    def test_empty_feedback_returns_empty(self):
        assert parse_replan_capabilities(None) == []
        assert parse_replan_capabilities("") == []


class TestHitl2Routing:
    def test_replan_routes_to_planner(self):
        state = {"status": "replanning"}
        assert route_after_hitl_2(state) == "replan"

    def test_approved_routes_to_complete(self):
        state = {"status": "complete"}
        assert route_after_hitl_2(state) == "complete"

    def test_approve_decision(self):
        state = {"run_id": "r1", "replan_rounds": 0}
        result = _apply_checkpoint_2_decision("approve", state)
        assert result["status"] == "complete"
        assert result["committee_decision"] == "approve"

    def test_reject_decision(self):
        state = {"run_id": "r1", "replan_rounds": 0}
        result = _apply_checkpoint_2_decision("reject", state)
        assert result["status"] == "rejected"

    def test_replan_clears_report_id(self):
        state = {
            "run_id": "r1",
            "replan_rounds": 0,
            "plan_revision": 0,
            "task_status": {},
            "report_id": "report_abc",
        }
        result = _apply_checkpoint_2_decision(
            {"action": "request_analysis", "feedback": "more valuation"},
            state,
        )
        assert result["report_id"] is None

    def test_request_analysis_clears_failed_tasks(self):
        state = {
            "run_id": "r1",
            "replan_rounds": 0,
            "plan_revision": 0,
            "task_status": {
                "t1": {"state": "failed", "capability": "valuation.estimate"},
                "t2": {"state": "succeeded", "capability": "company.profile"},
            },
        }
        result = _apply_checkpoint_2_decision(
            {"action": "request_analysis", "feedback": "redo valuation"},
            state,
        )
        assert result["status"] == "replanning"
        assert "t1" not in result["task_status"]
        assert "t2" in result["task_status"]
        assert result["plan_revision"] == 1
