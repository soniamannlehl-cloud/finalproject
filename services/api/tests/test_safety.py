"""
Safety pipeline tests.

Two properties matter more than the rest:

  1. A fabricated citation must hard-block a directional recommendation
     regardless of how confident the model is. Confidence is not evidence.
  2. "Not checked" must never present as "passed". A pipeline that returns
     green because it had nothing to examine manufactures false assurance,
     which is worse than having no pipeline at all.
"""

from datetime import datetime, timedelta, timezone
from unittest.mock import patch

import pytest
from contracts import (
    Criticality,
    IndustryPlaybook,
    ResearchPlan,
    Severity,
    SourceType,
    TaskSpec,
    TaskState,
    ValuationMethod,
)

from app.safety import deterministic, semantic

NOW = datetime.now(timezone.utc)


def evidence(capability="financials.ratios", source_type=SourceType.NEWS,
             age_days=0, eid="ev_1", confidence=0.9, degraded=False, content=None):
    return {
        "evidence_id": eid,
        "capability": capability,
        "source_type": source_type.value,
        "retrieved_at": NOW - timedelta(days=age_days),
        "confidence": confidence,
        "provider_degraded": degraded,
        "summary": "s",
        "citation": "c",
        "content": content or {},
    }


def claim(claim_id="c1", evidence_ids=None, text="a claim"):
    # `is None` rather than `or`: an explicitly EMPTY list is a distinct test
    # case (the uncited-claim path) and must not be replaced by the default.
    if evidence_ids is None:
        evidence_ids = ["ev_1"]
    return {"claim_id": claim_id, "text": text, "evidence_ids": evidence_ids}


class TestFreshness:
    def test_recent_news_is_fresh(self):
        findings, stale = deterministic.check_freshness([evidence(age_days=2)])
        assert findings == [] and stale == []

    def test_old_news_is_stale(self):
        findings, stale = deterministic.check_freshness([evidence(age_days=45)])
        assert len(findings) == 1
        assert stale == ["ev_1"]
        assert findings[0].severity == Severity.WARNING

    def test_filings_never_go_stale(self):
        """
        Filings are immutable once submitted. A blanket TTL would discard
        valid primary-source evidence.
        """
        _, stale = deterministic.check_freshness([
            evidence(source_type=SourceType.SEC_FILING, age_days=3000)
        ])
        assert stale == []

    def test_market_data_stales_quickly(self):
        _, stale = deterministic.check_freshness([
            evidence(source_type=SourceType.MARKET_DATA, age_days=3)
        ])
        assert stale == ["ev_1"]


class TestCitationValidation:
    def test_resolvable_citation_passes(self):
        findings, unsupported = deterministic.check_citations([claim()], {"ev_1"})
        assert findings == [] and unsupported == []

    def test_fabricated_citation_is_blocking(self):
        """The anti-fabrication guarantee, enforced by a set operation."""
        findings, unsupported = deterministic.check_citations(
            [claim(evidence_ids=["ev_DOES_NOT_EXIST"])], {"ev_1"}
        )
        assert unsupported == ["c1"]
        assert findings[0].severity == Severity.BLOCKING
        assert "do not resolve" in findings[0].message

    def test_partially_fabricated_citation_is_blocking(self):
        """One real citation does not launder a fabricated one alongside it."""
        _, unsupported = deterministic.check_citations(
            [claim(evidence_ids=["ev_1", "ev_FAKE"])], {"ev_1"}
        )
        assert unsupported == ["c1"]

    def test_empty_citation_list_is_blocking(self):
        findings, unsupported = deterministic.check_citations(
            [claim(evidence_ids=[])], {"ev_1"}
        )
        assert unsupported == ["c1"]
        assert findings[0].severity == Severity.BLOCKING


class TestCoverage:
    def _plan(self, capabilities_required: list[str]) -> ResearchPlan:
        return ResearchPlan(
            plan_id="p", run_id="r", ticker="X", company_name="X",
            classification=IndustryPlaybook.GENERIC, industry="i", sector="s",
            valuation_methods=[ValuationMethod.PE_MULTIPLE], required_metrics=["m"],
            tasks=[
                TaskSpec(task_id=f"task_{c.replace('.', '_')}", capability=c,
                         criticality=Criticality.REQUIRED, rationale="r")
                for c in capabilities_required
            ],
            fallback_strategy="f", planner_rationale="r", created_at=NOW,
        )

    def test_full_coverage_scores_one(self):
        plan = self._plan(["a.x", "b.y"])
        status = {
            "task_a_x": {"state": TaskState.SUCCEEDED.value},
            "task_b_y": {"state": TaskState.SUCCEEDED.value},
        }
        _, report = deterministic.check_coverage(plan, status, {"a.x": {}, "b.y": {}})
        assert report.coverage_ratio == 1.0

    def test_degraded_still_counts_as_covered(self):
        """Partial data is data; it lowers confidence, not coverage."""
        plan = self._plan(["a.x"])
        status = {"task_a_x": {"state": TaskState.DEGRADED.value}}
        _, report = deterministic.check_coverage(plan, status, {"a.x": {}})
        assert report.coverage_ratio == 1.0
        assert report.degraded_capabilities == ["a.x"]

    def test_task_succeeded_without_evidence_is_not_covered(self):
        """A green task that produced nothing is a coverage hole."""
        plan = self._plan(["a.x"])
        status = {"task_a_x": {"state": TaskState.SUCCEEDED.value}}
        _, report = deterministic.check_coverage(plan, status, {})
        assert report.failed_capabilities == ["a.x"]

    def test_majority_failure_is_blocking(self):
        plan = self._plan(["a.x", "b.y", "c.z", "d.w"])
        status = {"task_a_x": {"state": TaskState.SUCCEEDED.value}}
        findings, report = deterministic.check_coverage(plan, status, {"a.x": {}})
        assert report.coverage_ratio == 0.25
        assert any(f.severity == Severity.BLOCKING for f in findings)


class TestConfidenceConsistency:
    def test_thesis_confidence_far_above_evidence_is_flagged(self):
        """Confidence must not increase as it propagates upward."""
        findings = deterministic.check_confidence_consistency(
            [evidence(confidence=0.4), evidence(confidence=0.5, eid="ev_2")],
            thesis_confidence=0.95,
        )
        assert len(findings) == 1
        assert findings[0].check_name == "confidence_consistency"

    def test_proportionate_confidence_passes(self):
        assert deterministic.check_confidence_consistency(
            [evidence(confidence=0.9)], thesis_confidence=0.85
        ) == []

    def test_no_thesis_yet_is_not_flagged(self):
        assert deterministic.check_confidence_consistency([evidence()], None) == []


class TestSemanticSkipsAreHonest:
    """"Not checked" must never look like "passed"."""

    @patch("app.safety.semantic.get_settings")
    def test_no_llm_key_reports_skipped_not_passed(self, mock_settings):
        mock_settings.return_value.openai_api_key = ""
        result = semantic.run_semantic_checks([claim()], {"ev_1": evidence()})

        assert result.checks_run == []
        assert len(result.checks_skipped) == 2
        assert not result.was_verified
        assert all("NOT" in s["reason"] or "not" in s["reason"] for s in result.checks_skipped)

    @patch("app.safety.semantic.get_settings")
    def test_no_claims_reports_skipped(self, mock_settings):
        """Zero claims is not a clean bill of health."""
        mock_settings.return_value.openai_api_key = "sk-test"
        result = semantic.check_hallucination([], {})
        assert not result.was_verified
        assert result.checks_skipped[0]["check"] == "hallucination"

    @patch("app.safety.semantic.get_settings")
    def test_single_claim_cannot_contradict_itself(self, mock_settings):
        mock_settings.return_value.openai_api_key = "sk-test"
        result = semantic.check_contradiction([claim()])
        assert "at least two" in result.checks_skipped[0]["reason"]

    @patch("app.safety.semantic._llm_json", return_value=None)
    @patch("app.safety.semantic.get_settings")
    def test_llm_failure_reports_skipped_not_clean(self, mock_settings, _mock_llm):
        """An unreachable model must degrade to unverified, never to verified."""
        mock_settings.return_value.openai_api_key = "sk-test"
        mock_settings.return_value.resolve_model.return_value = "gpt-4o"
        result = semantic.check_hallucination([claim()], {"ev_1": evidence()})
        assert not result.was_verified
        assert "NOT verified" in result.checks_skipped[0]["reason"]

    @patch("app.safety.semantic._llm_json")
    @patch("app.safety.semantic.get_settings")
    def test_detected_hallucination_is_blocking(self, mock_settings, mock_llm):
        mock_settings.return_value.openai_api_key = "sk-test"
        mock_llm.return_value = {
            "results": [{"claim_id": "c1", "supported": False, "reason": "not in evidence"}]
        }
        result = semantic.check_hallucination([claim()], {"ev_1": evidence()})

        assert result.was_verified is False  # contradiction check hasn't run in isolation
        assert "hallucination" in result.checks_run
        assert result.unsupported_claim_ids == ["c1"]
        assert result.findings[0].severity == Severity.BLOCKING


class TestEvidenceRendering:
    """
    Regression: the checker was fed only `summary`, so claims citing specific
    figures were flagged unsupported because the renderer omitted them --
    penalising claims for the renderer's failure rather than their own.
    """

    def test_ratio_evidence_exposes_actual_values(self):
        rendered = semantic._render_evidence(evidence(
            capability="financials.ratios",
            content={"metrics": {
                "operating_margin": {"meaningful": True, "formatted": "60.4%"},
                "pe_ratio": {"meaningful": False, "flag": "negative earnings"},
            }},
        ))
        assert "operating_margin=60.4%" in rendered
        assert "not meaningful" in rendered

    def test_sentiment_evidence_exposes_headlines(self):
        rendered = semantic._render_evidence(evidence(
            capability="news.sentiment",
            content={"article_count": 2, "tone": "bull",
                     "articles": [{"title": "Record quarter"}, {"title": "New chip"}]},
        ))
        assert "Record quarter" in rendered
        assert "tone=bull" in rendered

    def test_valuation_evidence_exposes_implied_prices(self):
        rendered = semantic._render_evidence(evidence(
            capability="valuation.estimate",
            content={"results": [{"applicable": True, "label": "EV/EBITDA",
                                  "peer_median_multiple": 29.5,
                                  "implied_price_per_share": 175.35}]},
        ))
        assert "175.35" in rendered

    def test_rendering_is_truncated(self):
        rendered = semantic._render_evidence(evidence(
            capability="news.sentiment",
            content={"articles": [{"title": "x" * 500} for _ in range(20)]},
        ))
        assert len(rendered) <= 1200

    def test_unknown_capability_falls_back_to_summary(self):
        rendered = semantic._render_evidence(
            {"capability": "unknown.thing", "content": {}, "summary": "fallback text"}
        )
        assert rendered == "fallback text"
