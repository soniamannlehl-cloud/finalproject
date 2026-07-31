"""
Checkpoint #1 decision handling and post-validation routing.

Tests the pure functions -- the interrupt itself is exercised end-to-end
against the live stack, but the decision logic is worth isolating because
it is where a wrong branch silently researches the wrong company.
"""

import pytest

from app.graph.nodes.validate import _apply_checkpoint_1_decision, route_after_validation

TOP = {
    "ticker": "NVDA",
    "name": "NVIDIA Corporation",
    "sector": "Technology",
    "industry": "Semiconductors",
}
ALTERNATE = {
    "ticker": "NVDA.BA",
    "name": "NVIDIA CORP CEDEAR",
    "sector": "Technology",
    "industry": "Semiconductors",
}
CANDIDATES = [TOP, ALTERNATE]


def apply(decision):
    return _apply_checkpoint_1_decision(decision, TOP, CANDIDATES, "ev_1", attempts=1)


class TestConfirmation:
    @pytest.mark.parametrize("action", ["confirm", "yes", "y", "true", "CONFIRM", "  confirm  "])
    def test_accepts_affirmative_forms(self, action):
        """The API shouldn't have to normalize client input before the graph sees it."""
        result = apply({"action": action})
        assert result["checkpoint_1_confirmed"] is True
        assert result["ticker"] == "NVDA"
        assert result["status"] == "validated"

    def test_accepts_bare_string(self):
        """LangGraph resume values may arrive unwrapped."""
        assert apply("confirm")["checkpoint_1_confirmed"] is True

    def test_carries_classification_forward(self):
        """Sector/industry feed the Planner's playbook selection in M2."""
        result = apply({"action": "confirm"})
        assert result["sector"] == "Technology"
        assert result["industry"] == "Semiconductors"

    def test_records_validation_evidence(self):
        assert apply({"action": "confirm"})["evidence_ids"] == ["ev_1"]


class TestAlternateSelection:
    def test_selects_named_candidate(self):
        result = apply({"action": "confirm", "ticker": "NVDA.BA"})
        assert result["ticker"] == "NVDA.BA"
        assert result["company_name"] == "NVIDIA CORP CEDEAR"

    def test_unknown_ticker_falls_back_to_top_match(self):
        """A stale or malformed client selection must not research nothing."""
        result = apply({"action": "confirm", "ticker": "DOES.NOT.EXIST"})
        assert result["ticker"] == "NVDA"


class TestRejection:
    @pytest.mark.parametrize("action", ["reject", "no", "", "something_unexpected"])
    def test_anything_not_affirmative_is_a_rejection(self, action):
        """Fail closed: only an explicit yes proceeds to spend money on research."""
        result = apply({"action": action})
        assert result["checkpoint_1_confirmed"] is False
        assert result["status"] == "validation_rejected"

    def test_rejection_leaves_no_ticker_set(self):
        """A rejected run must not leak a half-confirmed company downstream."""
        assert "ticker" not in apply({"action": "reject"})


class TestRouting:
    def test_confirmed_validation_proceeds(self):
        state = {"status": "validated", "checkpoint_1_confirmed": True}
        assert route_after_validation(state) == "validated"

    @pytest.mark.parametrize("state", [
        {"status": "validation_rejected", "checkpoint_1_confirmed": False},
        {"status": "validation_failed"},
        {"status": "validation_unavailable"},
        {},
    ])
    def test_every_other_path_stops(self, state):
        assert route_after_validation(state) == "stop"

    def test_validated_status_without_confirmation_does_not_proceed(self):
        """Guards against a state where status was set but the human never confirmed."""
        state = {"status": "validated", "checkpoint_1_confirmed": None}
        assert route_after_validation(state) == "stop"
