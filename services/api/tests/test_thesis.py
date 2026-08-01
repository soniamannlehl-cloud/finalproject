"""
Thesis signal extraction and stance computation tests.

The property that matters most: the stance must follow the evidence. A
language model asked to form a view will produce a confident narrative
regardless of what the data supports, so the stance is derived here from
measured values and the model only writes prose around it. These tests are
what hold that guarantee in place.
"""

import pytest
from contracts import Polarity, ThesisVersion

from app.thesis.agent import _change_reason
from app.thesis.framework import build_structured_thesis
from app.thesis.signals import Signal, _ordinal, compute_stance, extract_signals


def ev(capability: str, content: dict, eid: str = "ev_1") -> dict:
    return {"evidence_id": eid, "capability": capability, "content": content}


def metric(value, formatted="x", meaningful=True):
    return {"value": value, "formatted": formatted, "meaningful": meaningful}


def signal(polarity: Polarity, strength: float = 0.5) -> Signal:
    return Signal("s", polarity, strength, "detail", "ev_1", "cap")


class TestOrdinal:
    @pytest.mark.parametrize("n,expected", [
        (1, "1st"), (2, "2nd"), (3, "3rd"), (4, "4th"),
        (11, "11th"), (12, "12th"), (13, "13th"),  # the exceptions
        (21, "21st"), (83, "83rd"), (100, "100th"),
    ])
    def test_formats_correctly(self, n, expected):
        """This text reaches the final report; '83th' would look sloppy."""
        assert _ordinal(n) == expected


class TestFinancialSignals:
    def test_strong_growth_is_bullish(self):
        signals = extract_signals([ev("financials.ratios", {
            "metrics": {"revenue_growth": metric(0.85, "85.0%")}
        })])
        assert [s.polarity for s in signals] == [Polarity.BULL]

    def test_revenue_decline_is_bearish(self):
        signals = extract_signals([ev("financials.ratios", {
            "metrics": {"revenue_growth": metric(-0.15, "-15.0%")}
        })])
        assert [s.polarity for s in signals] == [Polarity.BEAR]

    def test_operating_losses_are_bearish(self):
        signals = extract_signals([ev("financials.ratios", {
            "metrics": {"operating_margin": metric(-0.2, "-20.0%")}
        })])
        assert signals[0].polarity == Polarity.BEAR
        assert signals[0].name == "operating_losses"

    def test_cash_burn_is_bearish(self):
        signals = extract_signals([ev("financials.ratios", {
            "metrics": {"free_cash_flow": metric(-5e8, "-$500M")}
        })])
        assert signals[0].name == "cash_burn"

    def test_high_leverage_is_bearish(self):
        signals = extract_signals([ev("financials.ratios", {
            "metrics": {"debt_to_ebitda": metric(6.0, "6.00x")}
        })])
        assert signals[0].name == "high_leverage"

    def test_unmeasurable_metric_yields_no_signal(self):
        """
        Missing data must not become a directional view. Treating an
        uncomputable metric as a signal would manufacture conviction.
        """
        signals = extract_signals([ev("financials.ratios", {
            "metrics": {"debt_to_ebitda": metric(None, "n/a", meaningful=False)}
        })])
        assert signals == []


class TestValuationSignals:
    def test_trading_below_peer_value_is_bullish(self):
        signals = extract_signals([ev("valuation.estimate", {
            "valuation_range": {"vs_current_pct": 35.0}
        })])
        assert signals[0].polarity == Polarity.BULL

    def test_trading_above_peer_value_is_bearish(self):
        signals = extract_signals([ev("valuation.estimate", {
            "valuation_range": {"vs_current_pct": -26.0}
        })])
        assert signals[0].polarity == Polarity.BEAR

    def test_fairly_valued_yields_no_signal(self):
        """A small gap is noise, not a finding."""
        signals = extract_signals([ev("valuation.estimate", {
            "valuation_range": {"vs_current_pct": 3.0}
        })])
        assert signals == []


class TestSentimentSignals:
    def test_low_coverage_yields_no_signal(self):
        """
        Thin coverage is absence of information, not neutral sentiment.
        Deriving a signal from silence would fabricate conviction.
        """
        signals = extract_signals([ev("news.sentiment", {
            "low_coverage": True, "article_count": 2, "tone": "bull"
        })])
        assert signals == []

    def test_zero_articles_yields_no_signal(self):
        signals = extract_signals([ev("news.sentiment", {
            "article_count": 0, "tone": "neutral"
        })])
        assert signals == []

    def test_negative_tone_with_coverage_is_bearish(self):
        signals = extract_signals([ev("news.sentiment", {
            "low_coverage": False, "article_count": 12, "tone": "bear"
        })])
        assert signals[0].polarity == Polarity.BEAR


class TestRiskSignals:
    def test_high_severity_risk_weighs_more(self):
        signals = extract_signals([ev("risk.analysis", {
            "detected_risks": [
                {"id": "high_leverage", "severity": "high", "title": "T", "detail": "d"},
                {"id": "rich_valuation", "severity": "medium", "title": "T", "detail": "d"},
            ]
        })])
        assert all(s.polarity == Polarity.BEAR for s in signals)
        assert signals[0].strength > signals[1].strength


class TestExtractionResilience:
    def test_malformed_evidence_does_not_abort_extraction(self):
        """One bad record must not cost the run its entire thesis."""
        records = [
            ev("financials.ratios", {"metrics": None}),          # malformed
            ev("valuation.estimate", {"valuation_range": {"vs_current_pct": 40.0}}, "ev_2"),
        ]
        signals = extract_signals(records)
        assert len(signals) == 1

    def test_unknown_capability_is_ignored(self):
        assert extract_signals([ev("company.profile", {"name": "X"})]) == []


class TestStanceComputation:
    def test_no_signals_is_neutral_with_zero_confidence(self):
        assert compute_stance([]) == (Polarity.NEUTRAL, 0.0)

    def test_unanimous_bull_signals_produce_bull(self):
        stance, confidence = compute_stance([signal(Polarity.BULL, 0.8) for _ in range(5)])
        assert stance == Polarity.BULL
        assert confidence > 0.7

    def test_unanimous_bear_signals_produce_bear(self):
        stance, _ = compute_stance([signal(Polarity.BEAR, 0.8) for _ in range(4)])
        assert stance == Polarity.BEAR

    def test_evenly_split_evidence_is_neutral(self):
        """Genuinely mixed evidence is reported as mixed, not forced into a call."""
        stance, _ = compute_stance([
            signal(Polarity.BULL, 0.7), signal(Polarity.BEAR, 0.7),
            signal(Polarity.BULL, 0.5), signal(Polarity.BEAR, 0.5),
        ])
        assert stance == Polarity.NEUTRAL

    def test_conflict_reduces_confidence_versus_agreement(self):
        """
        Five signals agreeing is a stronger position than five split 3-2,
        even though both rest on five data points.
        """
        _, agreed = compute_stance([signal(Polarity.BULL, 0.8) for _ in range(5)])
        _, conflicted = compute_stance(
            [signal(Polarity.BULL, 0.8) for _ in range(3)]
            + [signal(Polarity.BEAR, 0.8) for _ in range(2)]
        )
        assert agreed > conflicted

    def test_more_corroborating_signals_raise_confidence(self):
        _, few = compute_stance([signal(Polarity.BULL, 0.8) for _ in range(2)])
        _, many = compute_stance([signal(Polarity.BULL, 0.8) for _ in range(8)])
        assert many > few

    def test_confidence_never_exceeds_ceiling(self):
        _, confidence = compute_stance([signal(Polarity.BULL, 1.0) for _ in range(50)])
        assert confidence <= 0.95


class TestStructuredThesisFallback:
    """Framework produces a usable primary thesis without an LLM."""

    def test_no_signals_yields_pending_primary_thesis(self):
        fw = build_structured_thesis(
            company="Acme",
            ticker="ACME",
            evidence_records=[],
            state={"task_status": {}},
        )
        assert "insufficient" in fw.primary_thesis.lower() or "pending" in fw.supporting_drivers[0].lower()


class TestChangeReason:
    def _prior(self, stance=Polarity.BULL, confidence=0.8) -> ThesisVersion:
        from datetime import datetime, timezone
        return ThesisVersion(
            version=1, run_id="r1", statement="s", stance=stance,
            confidence=confidence, change_reason="initial", triggered_by="t",
            created_at=datetime.now(timezone.utc),
        )

    def test_first_version_is_labeled_initial(self):
        assert "Initial" in _change_reason(None, Polarity.BULL, 0.8, 5)

    def test_stance_reversal_is_reported(self):
        reason = _change_reason(self._prior(Polarity.BULL), Polarity.BEAR, 0.7, 6)
        assert "revised from bull to bear" in reason

    def test_confidence_drop_reports_weakening(self):
        """
        Regression: a real 0.92 -> 0.87 move was previously reported as
        "stable", understating a genuine weakening.
        """
        reason = _change_reason(self._prior(confidence=0.92), Polarity.BULL, 0.87, 7)
        assert "weakened" in reason
        assert "0.92" in reason and "0.87" in reason

    def test_confidence_rise_reports_strengthening(self):
        reason = _change_reason(self._prior(confidence=0.60), Polarity.BULL, 0.85, 7)
        assert "strengthened" in reason

    def test_negligible_change_reports_reaffirmation(self):
        reason = _change_reason(self._prior(confidence=0.80), Polarity.BULL, 0.805, 7)
        assert "reaffirmed" in reason
