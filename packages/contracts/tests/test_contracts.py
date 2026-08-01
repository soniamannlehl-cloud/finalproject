"""
Tests for the shared contracts.

These cover the invariants the rest of the platform relies on: that an
uncited claim cannot exist, that a malformed plan is rejected before
execution, and that the recommendation gate refuses to opine on thin
evidence. All pure logic -- no network, no LLM, no database.
"""

from datetime import datetime, timedelta, timezone

import pytest
from pydantic import ValidationError

from contracts import (
    AgentCard,
    AgentRegistry,
    AgentSkill,
    Claim,
    CoverageReport,
    Criticality,
    Evidence,
    IndustryPlaybook,
    RecommendationAction,
    ResearchPlan,
    SafetyFinding,
    SafetyReport,
    Severity,
    SourceType,
    TaskSpec,
    ValuationMethod,
    apply_recommendation_gate,
    compute_evidence_score,
)

NOW = datetime.now(timezone.utc)


# --------------------------------------------------------------------------
# helpers
# --------------------------------------------------------------------------

def make_evidence(**overrides) -> Evidence:
    defaults = dict(
        evidence_id="ev_test", run_id="r1", task_id="t1", agent_id="a1",
        capability="financials.ratios", source_type=SourceType.NEWS,
        source_name="NewsAPI", citation="NewsAPI", content={},
        retrieved_at=NOW, confidence=0.8,
    )
    return Evidence(**{**defaults, **overrides})


def make_task(task_id: str, capability: str = "x", depends_on=None) -> TaskSpec:
    return TaskSpec(
        task_id=task_id, capability=capability,
        depends_on=depends_on or [], rationale="test",
    )


def make_plan(tasks: list[TaskSpec]) -> ResearchPlan:
    return ResearchPlan(
        plan_id="p1", run_id="r1", ticker="NVDA", company_name="NVIDIA",
        classification=IndustryPlaybook.TECHNOLOGY, industry="Semiconductors",
        sector="Technology", valuation_methods=[ValuationMethod.EV_REVENUE],
        required_metrics=["rule_of_40"], tasks=tasks,
        fallback_strategy="degrade gracefully", planner_rationale="test",
        created_at=NOW,
    )


def make_safety(*, coverage=1.0, evidence_score=None, unsupported=None,
                findings=None, contradictions=0) -> SafetyReport:
    required = ["a", "b", "c", "d"]
    n = round(coverage * len(required))
    return SafetyReport(
        run_id="r1",
        coverage=CoverageReport(
            required_capabilities=required,
            satisfied_capabilities=required[:n],
            failed_capabilities=required[n:],
        ),
        evidence_score=evidence_score if evidence_score is not None else coverage,
        unsupported_claim_ids=unsupported or [],
        contradiction_count=contradictions,
        findings=findings or [],
        created_at=NOW,
    )


# --------------------------------------------------------------------------
# Evidence
# --------------------------------------------------------------------------

class TestEvidence:
    def test_ids_are_content_addressed(self):
        """Identical content must dedupe across retries within the same run."""
        a = Evidence.make_id("agent", "cap", {"pe": 24.3}, "run_1")
        b = Evidence.make_id("agent", "cap", {"pe": 24.3}, "run_1")
        assert a == b
        assert Evidence.make_id("agent", "cap", {"pe": 24.3}, "run_1") != \
               Evidence.make_id("agent", "cap", {"pe": 24.3}, "run_2")

    def test_different_content_yields_different_ids(self):
        assert Evidence.make_id("agent", "cap", {"pe": 24.3}, "run_1") != \
               Evidence.make_id("agent", "cap", {"pe": 25.0}, "run_1")

    def test_naive_datetime_rejected(self):
        """Naive datetimes silently corrupt freshness math across services."""
        with pytest.raises(ValidationError):
            make_evidence(retrieved_at=datetime.now())

    @pytest.mark.parametrize("source_type,age_days,expected_stale", [
        (SourceType.NEWS, 1, False),
        (SourceType.NEWS, 45, True),
        (SourceType.MARKET_DATA, 2, True),
        (SourceType.SEC_FILING, 4000, False),          # immutable once filed
        (SourceType.FINANCIAL_STATEMENT, 4000, False),  # immutable once reported
    ])
    def test_freshness_policy(self, source_type, age_days, expected_stale):
        ev = make_evidence(
            source_type=source_type,
            retrieved_at=NOW - timedelta(days=age_days),
        )
        assert ev.is_stale(NOW) is expected_stale


# --------------------------------------------------------------------------
# Claim -- the anti-fabrication guardrail
# --------------------------------------------------------------------------

class TestClaim:
    def test_uncited_claim_is_unconstructible(self):
        """The core guardrail, enforced by the type system rather than a prompt."""
        with pytest.raises(ValidationError):
            Claim(
                claim_id="c1", run_id="r1", text="NVDA is undervalued",
                evidence_ids=[], confidence=0.9, category="valuation",
                author_agent_id="a1", created_at=NOW,
            )

    def test_cited_claim_accepted(self):
        claim = Claim(
            claim_id="c1", run_id="r1", text="Revenue grew 94% YoY",
            evidence_ids=["ev_1"], confidence=0.9, category="financial",
            author_agent_id="a1", created_at=NOW,
        )
        assert claim.evidence_ids == ["ev_1"]

    def test_duplicate_citations_rejected(self):
        with pytest.raises(ValidationError):
            Claim(
                claim_id="c1", run_id="r1", text="x",
                evidence_ids=["ev_1", "ev_1"], confidence=0.9,
                category="financial", author_agent_id="a1", created_at=NOW,
            )


# --------------------------------------------------------------------------
# ResearchPlan -- validated because an LLM produces it
# --------------------------------------------------------------------------

class TestResearchPlan:
    def test_execution_layers_group_parallel_work(self):
        plan = make_plan([
            make_task("t1"), make_task("t2"), make_task("t3"),
            make_task("t4", depends_on=["t3"]),
            make_task("t5", depends_on=["t3", "t4"]),
        ])
        layers = plan.execution_layers()
        assert [len(layer) for layer in layers] == [3, 1, 1]
        assert {t.task_id for t in layers[0]} == {"t1", "t2", "t3"}
        assert layers[1][0].task_id == "t4"
        assert layers[2][0].task_id == "t5"

    def test_independent_tasks_form_single_layer(self):
        plan = make_plan([make_task(f"t{i}") for i in range(5)])
        assert len(plan.execution_layers()) == 1

    def test_cycle_rejected(self):
        with pytest.raises(ValidationError, match="cycle"):
            make_plan([
                make_task("a", depends_on=["b"]),
                make_task("b", depends_on=["a"]),
            ])

    def test_unknown_dependency_rejected(self):
        with pytest.raises(ValidationError, match="unknown"):
            make_plan([make_task("a", depends_on=["ghost"])])

    def test_self_dependency_rejected(self):
        with pytest.raises(ValidationError, match="itself"):
            make_plan([make_task("a", depends_on=["a"])])

    def test_duplicate_task_ids_rejected(self):
        with pytest.raises(ValidationError, match="duplicate"):
            make_plan([make_task("a"), make_task("a")])

    def test_required_capabilities_excludes_optional(self):
        plan = make_plan([
            TaskSpec(task_id="t1", capability="req.cap",
                     criticality=Criticality.REQUIRED, rationale="r"),
            TaskSpec(task_id="t2", capability="opt.cap",
                     criticality=Criticality.OPTIONAL, rationale="r"),
        ])
        assert plan.required_capabilities() == {"req.cap"}


# --------------------------------------------------------------------------
# A2A discovery
# --------------------------------------------------------------------------

class TestAgentRegistry:
    @pytest.fixture
    def registry(self) -> AgentRegistry:
        return AgentRegistry(cards=[
            AgentCard(
                agent_id="financial_analyst", name="Financial", description="d",
                endpoint="http://specialists:8081/a2a",
                skills=[AgentSkill(skill_id="s1", name="Ratios", description="d",
                                   capability="financials.ratios")],
            )
        ])

    def test_resolves_capability_to_agent(self, registry):
        assert registry.resolve("financials.ratios").agent_id == "financial_analyst"

    def test_unknown_capability_resolves_to_none(self, registry):
        assert registry.resolve("earnings.call") is None

    def test_missing_reports_unserviceable_capabilities(self, registry):
        missing = registry.missing({"financials.ratios", "earnings.call"})
        assert missing == {"earnings.call"}


# --------------------------------------------------------------------------
# Recommendation gate -- the "never opine on thin evidence" guarantee
# --------------------------------------------------------------------------

class TestRecommendationGate:
    def test_strong_evidence_permits_directional_call(self):
        result = apply_recommendation_gate(
            RecommendationAction.BUY, confidence=0.85, safety=make_safety(coverage=1.0)
        )
        assert result.permitted_action == RecommendationAction.BUY
        assert not result.was_downgraded
        assert result.is_directional

    def test_low_coverage_blocks_any_call(self):
        result = apply_recommendation_gate(
            RecommendationAction.BUY, confidence=0.95, safety=make_safety(coverage=0.25)
        )
        assert result.permitted_action == RecommendationAction.INSUFFICIENT_EVIDENCE
        assert result.was_downgraded

    def test_low_confidence_downgrades_to_hold(self):
        result = apply_recommendation_gate(
            RecommendationAction.BUY, confidence=0.55, safety=make_safety(coverage=1.0)
        )
        assert result.permitted_action == RecommendationAction.HOLD
        assert result.was_downgraded

    def test_fabricated_citation_hard_blocks_regardless_of_confidence(self):
        """An unresolvable citation outranks every other signal."""
        result = apply_recommendation_gate(
            RecommendationAction.BUY, confidence=0.99,
            safety=make_safety(coverage=1.0, unsupported=["c9"]),
        )
        assert result.permitted_action == RecommendationAction.INSUFFICIENT_EVIDENCE

    def test_blocking_finding_hard_blocks(self):
        finding = SafetyFinding(
            finding_id="f1", check_name="hallucination", severity=Severity.BLOCKING,
            message="unsupported growth claim", detected_at=NOW,
        )
        result = apply_recommendation_gate(
            RecommendationAction.BUY, confidence=0.99,
            safety=make_safety(coverage=1.0, findings=[finding]),
        )
        assert result.permitted_action == RecommendationAction.INSUFFICIENT_EVIDENCE

    def test_excess_contradictions_downgrade_to_hold(self):
        result = apply_recommendation_gate(
            RecommendationAction.BUY, confidence=0.9,
            safety=make_safety(coverage=1.0, contradictions=5),
        )
        assert result.permitted_action == RecommendationAction.HOLD

    def test_hold_is_not_downgraded_by_low_confidence(self):
        """Only directional calls are confidence-gated."""
        result = apply_recommendation_gate(
            RecommendationAction.HOLD, confidence=0.4,
            safety=make_safety(coverage=1.0),
        )
        assert result.permitted_action == RecommendationAction.HOLD
        assert not result.was_downgraded


class TestEvidenceScore:
    def test_full_coverage_scores_one(self):
        assert compute_evidence_score(1.0) == 1.0

    def test_zero_coverage_scores_zero(self):
        assert compute_evidence_score(0.0) == 0.0

    def test_staleness_discounts_score(self):
        assert compute_evidence_score(1.0, stale_fraction=1.0) == pytest.approx(0.70)

    def test_degradation_discounts_score(self):
        assert compute_evidence_score(1.0, degraded_fraction=1.0) == pytest.approx(0.85)

    def test_score_never_exceeds_bounds(self):
        assert 0.0 <= compute_evidence_score(1.0, 1.0, 1.0) <= 1.0
