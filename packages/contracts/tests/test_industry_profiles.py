"""Tests for industry profile registry and configuration."""

from contracts import Capability, IndustryPlaybook, ValuationMethod
from contracts.industry_profiles import PROFILES, classify, get_profile


class TestIndustryProfiles:
    def test_all_requested_industries_exist(self):
        expected = {
            IndustryPlaybook.TECHNOLOGY,
            IndustryPlaybook.BANKING,
            IndustryPlaybook.INSURANCE,
            IndustryPlaybook.HEALTHCARE,
            IndustryPlaybook.ENERGY,
            IndustryPlaybook.RETAIL,
            IndustryPlaybook.MANUFACTURING,
            IndustryPlaybook.CONSUMER_STAPLES,
            IndustryPlaybook.REIT,
            IndustryPlaybook.TELECOMMUNICATIONS,
            IndustryPlaybook.INDUSTRIALS,
        }
        assert expected <= set(PROFILES.keys())

    def test_each_profile_has_full_configuration(self):
        for profile_id, profile in PROFILES.items():
            if profile_id == IndustryPlaybook.GENERIC:
                continue
            assert profile.required_financial_metrics
            assert profile.valuation_methods
            assert profile.key_performance_indicators
            assert profile.business_risks
            assert profile.competitive_factors
            assert profile.investment_drivers
            assert profile.business_model
            assert Capability.INVESTMENT_DRIVERS.value in profile.required_capabilities

    def test_bank_and_reit_valuation_methods_differ(self):
        bank = get_profile(IndustryPlaybook.BANKING)
        reit = get_profile(IndustryPlaybook.REIT)
        assert ValuationMethod.PRICE_BOOK in bank.valuation_methods
        assert ValuationMethod.FFO_MULTIPLE in reit.valuation_methods
        assert ValuationMethod.PE_MULTIPLE not in reit.valuation_methods

    def test_classify_insurance(self):
        pid, _ = classify("Financial Services", "Insurance - Property & Casualty")
        assert pid == IndustryPlaybook.INSURANCE

    def test_profile_serializes_for_task_inputs(self):
        profile = get_profile(IndustryPlaybook.TECHNOLOGY)
        payload = profile.task_payload()
        assert payload["profile_id"] == "technology"
        assert "required_financial_metrics" in payload
        assert "investment_drivers" in payload
