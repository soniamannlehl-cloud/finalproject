"""Tests for the recommendation synthesizer and policy gate integration."""

from datetime import datetime, timezone

from contracts import RecommendationAction, SafetyReport, CoverageReport

from app.graph.nodes.synthesizer import _to_action, _position


class TestSynthesizerHelpers:
    def test_valid_action(self):
        assert _to_action("buy") == RecommendationAction.BUY

    def test_invalid_action_defaults_to_insufficient(self):
        assert _to_action("maybe") == RecommendationAction.INSUFFICIENT_EVIDENCE

    def test_position_from_dict(self):
        pos = _position({"argument": "Strong growth", "conviction": 0.8, "claim_ids": ["c1"]}, "bull_analyst")
        assert pos.argument == "Strong growth"
        assert pos.conviction == 0.8
        assert pos.claim_ids == ["c1"]

    def test_position_defaults_on_none(self):
        pos = _position(None, "bear_analyst")
        assert pos.role == "bear_analyst"
        assert pos.conviction == 0.0


class TestPolicyGateIntegration:
    def test_low_evidence_score_blocks_directional(self):
        from contracts import apply_recommendation_gate

        safety = SafetyReport(
            run_id="r1",
            coverage=CoverageReport(
                required_capabilities=["a"],
                satisfied_capabilities=["a"],
            ),
            evidence_score=0.40,
            created_at=datetime.now(timezone.utc),
        )
        gate = apply_recommendation_gate(RecommendationAction.BUY, 0.9, safety)
        assert gate.permitted_action == RecommendationAction.INSUFFICIENT_EVIDENCE
        assert gate.was_downgraded
