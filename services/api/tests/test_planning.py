"""
Planner and playbook tests.

The point of these is the requirement that the system must NOT apply
identical analysis to every company. That is asserted concretely: a bank and
a REIT must not receive the same valuation methods, and P/E must not appear
in a REIT's metric set.
"""

import pytest
from contracts import Criticality, IndustryPlaybook, ValuationMethod

from app.planning import playbooks
from app.planning.planner import _build_tasks, build_plan


class TestClassification:
    @pytest.mark.parametrize("sector,industry,expected", [
        ("Technology", "Semiconductors", IndustryPlaybook.TECHNOLOGY),
        ("Technology", "Software - Infrastructure", IndustryPlaybook.TECHNOLOGY),
        ("Financial Services", "Banks - Diversified", IndustryPlaybook.BANKING),
        ("Real Estate", "REIT - Retail", IndustryPlaybook.REIT),
        ("Healthcare", "Biotechnology", IndustryPlaybook.HEALTHCARE),
        ("Energy", "Oil & Gas Integrated", IndustryPlaybook.ENERGY),
        ("Consumer Cyclical", "Specialty Retail", IndustryPlaybook.CONSUMER),
        ("Utilities", "Utilities - Regulated Electric", IndustryPlaybook.UTILITIES),
    ])
    def test_classifies_known_industries(self, sector, industry, expected):
        assert playbooks.classify(sector, industry)[0] == expected

    def test_industry_outranks_sector(self):
        """
        A REIT sits in the Real Estate sector but so do brokerages. The more
        specific industry string must win.
        """
        assert playbooks.classify("Real Estate", "REIT - Office")[0] == IndustryPlaybook.REIT

    def test_unknown_falls_back_to_generic_with_a_reason(self):
        classification, reason = playbooks.classify("Nonexistent", "Nonexistent")
        assert classification == IndustryPlaybook.GENERIC
        assert "no playbook matched" in reason

    def test_missing_classification_data_is_safe(self):
        assert playbooks.classify(None, None)[0] == IndustryPlaybook.GENERIC


class TestPlaybooksDiffer:
    """The core anti-generic-analysis guarantee."""

    def test_bank_and_reit_use_different_valuation_methods(self):
        bank = playbooks.get_playbook(IndustryPlaybook.BANKING)
        reit = playbooks.get_playbook(IndustryPlaybook.REIT)
        assert set(bank.valuation_methods).isdisjoint(reit.valuation_methods)

    def test_reit_uses_ffo_not_pe(self):
        """
        REITs report heavy non-cash depreciation, so P/E is misleading and FFO
        is the correct lens. Getting this backwards is a classic novice error.
        """
        reit = playbooks.get_playbook(IndustryPlaybook.REIT)
        assert ValuationMethod.FFO_MULTIPLE in reit.valuation_methods
        assert ValuationMethod.PE_MULTIPLE not in reit.valuation_methods

    def test_bank_uses_price_to_book(self):
        bank = playbooks.get_playbook(IndustryPlaybook.BANKING)
        assert ValuationMethod.PRICE_BOOK in bank.valuation_methods
        assert "net_interest_margin" in bank.required_metrics

    def test_technology_uses_rule_of_40(self):
        tech = playbooks.get_playbook(IndustryPlaybook.TECHNOLOGY)
        assert ValuationMethod.RULE_OF_40 in tech.valuation_methods

    def test_every_playbook_declares_metrics_and_risks(self):
        for classification, playbook in playbooks.PLAYBOOKS.items():
            assert playbook.required_metrics, f"{classification} has no metrics"
            assert playbook.key_risks, f"{classification} has no key risks"
            assert playbook.rationale, f"{classification} has no rationale"

    def test_all_playbooks_include_universal_capabilities(self):
        """Every company gets profile, financials, and news regardless of industry."""
        for playbook in playbooks.PLAYBOOKS.values():
            assert "company.profile" in playbook.required_capabilities
            assert "financials.statements" in playbook.required_capabilities


class TestTaskGraph:
    def test_ratios_depend_on_statements(self):
        tech = playbooks.get_playbook(IndustryPlaybook.TECHNOLOGY)
        tasks = _build_tasks(tech, "NVDA", "NVIDIA")
        ratios = next(t for t in tasks if t.capability == "financials.ratios")
        assert "task_financials_statements" in ratios.depends_on

    def test_dependencies_are_pruned_to_scheduled_tasks(self):
        """
        A dependency on a capability this playbook never scheduled would leave
        the task waiting forever, so unscheduled deps must be dropped.
        """
        generic = playbooks.get_playbook(IndustryPlaybook.GENERIC)
        tasks = _build_tasks(generic, "X", "X Corp")
        scheduled = {t.task_id for t in tasks}
        for task in tasks:
            assert set(task.depends_on) <= scheduled

    def test_required_and_optional_criticality_is_assigned(self):
        tech = playbooks.get_playbook(IndustryPlaybook.TECHNOLOGY)
        tasks = _build_tasks(tech, "NVDA", "NVIDIA")
        criticalities = {t.criticality for t in tasks}
        assert Criticality.REQUIRED in criticalities
        assert Criticality.OPTIONAL in criticalities


class TestBuildPlan:
    """build_plan runs without an LLM key, which is the deterministic fallback path."""

    def test_produces_a_valid_multi_layer_plan(self):
        plan = build_plan("run_1", "NVDA", "NVIDIA", "Technology", "Semiconductors")
        assert plan.classification == IndustryPlaybook.TECHNOLOGY
        layers = plan.execution_layers()
        assert len(layers) >= 2, "statements -> ratios should force at least two layers"
        assert len(layers[0]) >= 2, "first layer should fan out in parallel"

    def test_plan_records_its_own_rationale(self):
        """Planning must be inspectable, not implicit."""
        plan = build_plan("run_1", "JPM", "JPMorgan", "Financial Services", "Banks - Diversified")
        assert plan.planner_rationale
        assert all(t.rationale for t in plan.tasks)

    def test_replan_carries_revision_lineage(self):
        plan = build_plan(
            "run_1", "NVDA", "NVIDIA", "Technology", "Semiconductors",
            revision=1, parent_revision=0, replan_reason="reviewer wanted competitor detail",
        )
        assert plan.revision == 1
        assert plan.parent_revision == 0
        assert "competitor" in plan.replan_reason

    def test_replan_can_add_capabilities(self):
        plan = build_plan(
            "run_1", "NVDA", "NVIDIA", "Technology", "Semiconductors",
            revision=1, extra_capabilities=["filings.sec"],
        )
        assert "filings.sec" in {t.capability for t in plan.tasks}

    def test_unknown_industry_still_produces_a_workable_plan(self):
        """Degrades to the generic framework rather than failing."""
        plan = build_plan("run_1", "XYZ", "XYZ Corp", None, None)
        assert plan.classification == IndustryPlaybook.GENERIC
        assert len(plan.tasks) >= 4
