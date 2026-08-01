"""Tests for report HTML rendering."""

from datetime import datetime, timezone

from contracts import (
    CommitteePosition,
    InvestmentReport,
    Polarity,
    Recommendation,
    RecommendationAction,
    ReportSection,
    ThesisVersion,
)

from app.report.renderer import render_html


def _minimal_report() -> InvestmentReport:
    now = datetime.now(timezone.utc)
    rec = Recommendation(
        run_id="r1", ticker="NVDA", action=RecommendationAction.HOLD,
        confidence=0.7, evidence_score=0.75,
        bull_case=CommitteePosition(role="bull", argument="Growth.", conviction=0.8),
        bear_case=CommitteePosition(role="bear", argument="Valuation.", conviction=0.6),
        cio_rationale="Balanced view.", created_at=now,
    )
    thesis = ThesisVersion(
        run_id="r1", version=1, statement="Constructive on AI leadership.",
        stance=Polarity.BULL, confidence=0.7, change_reason="initial",
        triggered_by="test", created_at=now,
    )
    return InvestmentReport(
        report_id="rep1", run_id="r1", ticker="NVDA", company_name="NVIDIA",
        generated_at=now, recommendation=rec, final_thesis=thesis,
        sections=[ReportSection(section_id="exec", title="Executive Summary", order=1, body="Test.")],
    )


class TestReportRenderer:
    def test_render_html_contains_company(self):
        html = render_html(_minimal_report())
        assert "NVIDIA" in html
        assert "NVDA" in html
        assert "hold" in html.lower()
