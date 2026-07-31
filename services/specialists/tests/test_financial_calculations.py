"""
Deterministic financial calculation tests.

These matter more than most tests in the platform: every number the final
report states originates here. The "not meaningful" cases get the most
attention, because silently emitting a P/E for a loss-making company -- or
omitting it with no explanation -- are both ways to mislead a reader.
"""

import pytest

from app.tools.financial_calculations import (
    compute_all, current_ratio, debt_to_ebitda, debt_to_equity, ev_to_ebitda,
    ev_to_revenue, free_cash_flow, gross_margin, net_margin, operating_margin,
    pe_ratio, price_to_book, return_on_assets, return_on_equity, revenue_growth,
    rule_of_40,
)


class TestNotMeaningfulCases:
    """A wrong number is worse than an honest 'not meaningful'."""

    def test_negative_earnings_has_no_meaningful_pe(self):
        result = pe_ratio(price=100.0, eps=-2.5)
        assert result.value is None
        assert not result.meaningful
        assert "negative" in result.flag

    def test_zero_earnings_has_no_meaningful_pe(self):
        assert not pe_ratio(price=100.0, eps=0.0).meaningful

    def test_negative_book_value_has_no_meaningful_pb(self):
        assert not price_to_book(price=50.0, book_value_per_share=-3.0).meaningful

    def test_negative_equity_has_no_meaningful_roe(self):
        assert not return_on_equity(net_income=1e9, equity=-5e8).meaningful

    def test_negative_equity_has_no_meaningful_debt_to_equity(self):
        assert not debt_to_equity(total_debt=1e9, equity=-5e8).meaningful

    def test_negative_ebitda_has_no_meaningful_multiple(self):
        assert not ev_to_ebitda(enterprise_value=1e10, ebitda=-2e8).meaningful
        assert not debt_to_ebitda(total_debt=1e9, ebitda=-2e8).meaningful

    def test_missing_inputs_are_flagged_not_guessed(self):
        result = pe_ratio(price=None, eps=5.0)
        assert result.value is None
        assert "unavailable" in result.flag

    def test_zero_prior_revenue_avoids_division_by_zero(self):
        assert not revenue_growth(current=1e9, prior=0).meaningful


class TestCorrectValues:
    def test_pe_ratio(self):
        result = pe_ratio(price=100.0, eps=4.0)
        assert result.value == pytest.approx(25.0)
        assert result.formatted == "25.00x"

    def test_margins(self):
        assert gross_margin(60.0, 100.0).value == pytest.approx(0.60)
        assert operating_margin(25.0, 100.0).value == pytest.approx(0.25)
        assert net_margin(15.0, 100.0).value == pytest.approx(0.15)
        assert gross_margin(60.0, 100.0).formatted == "60.0%"

    def test_growth_handles_decline(self):
        result = revenue_growth(current=80.0, prior=100.0)
        assert result.value == pytest.approx(-0.20)
        assert result.meaningful

    def test_returns(self):
        assert return_on_equity(20.0, 100.0).value == pytest.approx(0.20)
        assert return_on_assets(10.0, 200.0).value == pytest.approx(0.05)

    def test_multiples(self):
        assert ev_to_revenue(1000.0, 250.0).value == pytest.approx(4.0)
        assert ev_to_ebitda(1000.0, 100.0).value == pytest.approx(10.0)

    def test_current_ratio(self):
        assert current_ratio(150.0, 100.0).value == pytest.approx(1.5)

    def test_free_cash_flow_treats_capex_sign_agnostically(self):
        """Providers report capex as either sign; both must yield the same FCF."""
        assert free_cash_flow(1000.0, -300.0).value == pytest.approx(700.0)
        assert free_cash_flow(1000.0, 300.0).value == pytest.approx(700.0)

    def test_free_cash_flow_can_be_negative(self):
        result = free_cash_flow(100.0, 400.0)
        assert result.value == pytest.approx(-300.0)
        assert result.meaningful, "negative FCF is a real finding, not an error"


class TestRuleOf40:
    def test_passing_score(self):
        result = rule_of_40(revenue_growth_pct=0.35, fcf_margin_pct=0.15)
        assert result.value == pytest.approx(50.0)
        assert "passes" in result.formatted

    def test_failing_score(self):
        result = rule_of_40(revenue_growth_pct=0.10, fcf_margin_pct=0.05)
        assert result.value == pytest.approx(15.0)
        assert "below" in result.formatted

    def test_high_growth_offsets_negative_margin(self):
        """The tradeoff the heuristic exists to encode."""
        assert rule_of_40(0.60, -0.10).value == pytest.approx(50.0)


class TestComputeAll:
    @pytest.fixture
    def financials(self):
        return {
            "price": 100.0, "eps": 4.0, "book_value_per_share": 20.0,
            "enterprise_value": 1000.0, "revenue": 250.0, "revenue_prior": 200.0,
            "gross_profit": 150.0, "operating_income": 60.0, "net_income": 40.0,
            "ebitda": 80.0, "total_debt": 100.0, "total_equity": 200.0,
            "total_assets": 400.0, "current_assets": 150.0, "current_liabilities": 100.0,
            "operating_cash_flow": 70.0, "capex": 20.0,
        }

    def test_computes_the_full_metric_set(self, financials):
        metrics = compute_all(financials)
        for name in ("pe_ratio", "gross_margin", "revenue_growth",
                     "free_cash_flow", "rule_of_40", "debt_to_equity"):
            assert name in metrics
            assert metrics[name]["meaningful"], f"{name} should be computable"

    def test_empty_input_flags_everything_rather_than_crashing(self):
        """A provider outage must degrade the metric set, not raise."""
        metrics = compute_all({})
        assert len(metrics) > 0
        assert all(not m["meaningful"] for m in metrics.values())
        assert all(m["flag"] for m in metrics.values())

    def test_partial_data_computes_what_it_can(self, financials):
        """Missing EBITDA shouldn't prevent margin calculations."""
        del financials["ebitda"]
        metrics = compute_all(financials)
        assert metrics["gross_margin"]["meaningful"]
        assert not metrics["ev_to_ebitda"]["meaningful"]

    def test_loss_making_company_flags_pe_but_computes_margins(self, financials):
        financials.update({"eps": -1.5, "net_income": -30.0})
        metrics = compute_all(financials)
        assert not metrics["pe_ratio"]["meaningful"]
        assert metrics["net_margin"]["meaningful"]
        assert metrics["net_margin"]["value"] < 0
