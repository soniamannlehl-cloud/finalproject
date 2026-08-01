"""Tests for the investment analyst thesis framework builder."""

from contracts import Polarity, RecommendationAction

from app.thesis.framework import build_structured_thesis


def ev(capability: str, content: dict, eid: str = "ev_1") -> dict:
    return {"evidence_id": eid, "capability": capability, "content": content}


class TestStructuredThesis:
    def test_builds_core_sections_from_evidence(self):
        records = [
            ev("financials.ratios", {
                "metrics": {"revenue_growth": {"value": 0.25, "formatted": "25%", "meaningful": True}}
            }),
            ev("valuation.estimate", {
                "valuation_range": {"vs_current_pct": 20.0}
            }, "ev_2"),
            ev("news.sentiment", {
                "tone": "bull", "article_count": 10, "low_coverage": False,
            }, "ev_3"),
        ]
        fw = build_structured_thesis(
            company="Acme Corp",
            ticker="ACME",
            evidence_records=records,
            state={"task_status": {}},
            recommendation={"action": RecommendationAction.BUY.value, "confidence": 0.8},
        )

        assert "3-5 years" in fw.core_question or "Acme" in fw.core_question
        assert fw.primary_thesis
        assert len(fw.supporting_drivers) >= 1
        assert fw.valuation_opinion == "cheap"
        assert fw.confidence > 0
        assert fw.recommendation == "buy"

    def test_insufficient_evidence_overrides_primary_thesis(self):
        fw = build_structured_thesis(
            company="Acme",
            ticker="ACME",
            evidence_records=[],
            state={"task_status": {}},
            recommendation={"action": RecommendationAction.INSUFFICIENT_EVIDENCE.value},
        )
        assert "too thin" in fw.primary_thesis.lower() or "additional research" in fw.primary_thesis.lower()
        assert fw.recommendation == "insufficient_evidence"

    def test_valuation_fair_in_mid_range(self):
        fw = build_structured_thesis(
            company="Acme",
            ticker="ACME",
            evidence_records=[ev("valuation.estimate", {"valuation_range": {"vs_current_pct": 5.0}})],
            state={},
        )
        assert fw.valuation_opinion == "fair"

    def test_bear_stance_core_question_uses_avoid(self):
        records = [
            ev("financials.ratios", {
                "metrics": {"revenue_growth": {"value": -0.2, "formatted": "-20%", "meaningful": True}}
            }),
            ev("valuation.estimate", {"valuation_range": {"vs_current_pct": -30.0}}, "ev_2"),
        ]
        fw = build_structured_thesis(
            company="Acme",
            ticker="ACME",
            evidence_records=records,
            state={},
        )
        assert "avoid" in fw.core_question.lower()
