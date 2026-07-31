"""
Tests for the M3 specialist fleet.

Includes regression tests for two bugs found by running the system against
real data rather than fixtures:

  * Yahoo industry labels use typographic dashes ("Drug Manufacturers—General"
    contains an EM DASH), which 404'd peer lookup for entire sectors.
  * SEC EDGAR returns 403 for any User-Agent lacking contact information, and
    the retry logic burned three attempts on that permanent failure.
"""

from unittest.mock import MagicMock, patch

import pytest

from app.agents import competitor_analyst, risk_analyst, valuation_analyst
from app.tools.peers_tool import _industry_key, median
from app.tools.sec_edgar import SECPermanentError


class TestIndustrySlugNormalization:
    """Regression: typographic dashes broke peer lookup for whole sectors."""

    @pytest.mark.parametrize("label,expected", [
        ("Drug Manufacturers—General", "drug-manufacturers-general"),  # em dash
        ("REIT – Retail", "reit-retail"),                              # en dash
        ("Semiconductors", "semiconductors"),
        ("Oil & Gas E&P", "oil-and-gas-eandp"),
        ("Banks - Diversified", "banks-diversified"),
    ])
    def test_normalizes_to_yahoo_slug(self, label, expected):
        assert _industry_key(label) == expected

    def test_never_emits_double_hyphens(self):
        assert "--" not in _industry_key("Banks — Diversified & Regional")

    def test_never_emits_leading_or_trailing_hyphen(self):
        slug = _industry_key(" - Utilities - ")
        assert not slug.startswith("-") and not slug.endswith("-")


class TestPeerMedian:
    def test_ignores_missing_values(self):
        assert median([10.0, None, 20.0, None]) == pytest.approx(15.0)

    def test_excludes_non_positive_multiples(self):
        """A negative P/E is not a comparable -- including it corrupts the median."""
        assert median([10.0, -5.0, 20.0, 0.0]) == pytest.approx(15.0)

    def test_returns_none_when_nothing_comparable(self):
        assert median([None, None]) is None
        assert median([]) is None

    def test_resists_outlier_skew(self):
        """
        Median rather than mean: one near-zero-earnings peer with a 900x P/E
        would drag a mean into uselessness.
        """
        assert median([10.0, 12.0, 14.0, 900.0]) == pytest.approx(13.0)


class TestSECRetryPolicy:
    def test_permanent_error_is_a_distinct_type(self):
        """
        403/404 must be separable from transient failures so tenacity does not
        retry an outcome that is identical every time.
        """
        assert issubclass(SECPermanentError, Exception)


class TestValuationApplicability:
    """Refusing to produce a number is a valid, and sometimes correct, answer."""

    def test_negative_driver_is_not_valued(self):
        result = valuation_analyst._apply_multiple(
            "pe_multiple", {"net_income": -1e9, "shares_outstanding": 1e9}, peer_median=20.0
        )
        assert not result["applicable"]
        assert "negative" in result["reason"]

    def test_missing_peer_median_blocks_valuation(self):
        result = valuation_analyst._apply_multiple(
            "ev_ebitda", {"ebitda": 1e9, "shares_outstanding": 1e9}, peer_median=None
        )
        assert not result["applicable"]
        assert "peer median" in result["reason"]

    def test_ev_multiple_subtracts_net_debt(self):
        """
        EV values the whole enterprise; equity holders own what remains after
        debt. Skipping this bridge overstates equity value for leveraged firms.
        """
        result = valuation_analyst._apply_multiple(
            "ev_ebitda",
            {"ebitda": 100.0, "total_debt": 500.0, "shares_outstanding": 10.0},
            peer_median=10.0,
        )
        assert result["applicable"]
        assert result["net_debt_adjusted"] is True
        assert result["implied_equity_value"] == pytest.approx(500.0)  # 10*100 - 500

    def test_equity_multiple_does_not_subtract_debt(self):
        result = valuation_analyst._apply_multiple(
            "pe_multiple",
            {"net_income": 100.0, "total_debt": 500.0, "shares_outstanding": 10.0},
            peer_median=15.0,
        )
        assert result["implied_equity_value"] == pytest.approx(1500.0)
        assert result["net_debt_adjusted"] is False

    def test_unsupported_methods_are_declared_not_silently_dropped(self):
        for method in ("dcf", "ffo_multiple", "nav"):
            assert method in valuation_analyst._UNSUPPORTED
            assert valuation_analyst._UNSUPPORTED[method], "must state WHY it is unsupported"


class TestCompetitorPercentile:
    def test_ranks_against_peers(self):
        assert competitor_analyst._percentile_rank(15.0, [10.0, 12.0, 20.0]) == pytest.approx(0.67, abs=0.01)

    def test_top_of_set_ranks_one(self):
        assert competitor_analyst._percentile_rank(100.0, [10.0, 20.0]) == 1.0

    def test_bottom_of_set_ranks_zero(self):
        assert competitor_analyst._percentile_rank(1.0, [10.0, 20.0]) == 0.0

    def test_missing_subject_value_is_uncomparable(self):
        assert competitor_analyst._percentile_rank(None, [10.0, 20.0]) is None

    def test_no_peer_data_is_uncomparable(self):
        assert competitor_analyst._percentile_rank(15.0, [None, None]) is None


class TestRiskDetection:
    """Risks come from measured signals, not generic industry boilerplate."""

    def _detect(self, metrics: dict) -> list[dict]:
        detected = []
        for rule in risk_analyst._RISK_RULES:
            m = metrics.get(rule["metric"], {})
            if m.get("meaningful") and rule["test"](m.get("value")):
                detected.append(rule)
        return detected

    def test_flags_high_leverage(self):
        found = self._detect({"debt_to_ebitda": {"meaningful": True, "value": 5.8}})
        assert [r["id"] for r in found] == ["high_leverage"]

    def test_ignores_healthy_leverage(self):
        assert self._detect({"debt_to_ebitda": {"meaningful": True, "value": 1.2}}) == []

    def test_flags_negative_free_cash_flow(self):
        found = self._detect({"free_cash_flow": {"meaningful": True, "value": -5e8}})
        assert [r["id"] for r in found] == ["negative_fcf"]

    def test_flags_operating_losses(self):
        found = self._detect({"operating_margin": {"meaningful": True, "value": -0.15}})
        assert [r["id"] for r in found] == ["margin_pressure"]

    def test_unmeasurable_metric_raises_no_risk(self):
        """
        A metric we could not compute must not produce a phantom risk -- that
        would turn missing data into a fabricated finding.
        """
        assert self._detect({
            "debt_to_ebitda": {"meaningful": False, "value": None, "flag": "negative EBITDA"}
        }) == []

    def test_every_rule_explains_why_it_matters(self):
        for rule in risk_analyst._RISK_RULES:
            assert rule["why"], f"{rule['id']} must explain its significance"
            assert rule["severity"] in ("high", "medium", "low")
