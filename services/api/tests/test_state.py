"""
State reducer tests.

These guard the invariant that breaks first and most confusingly under
parallelism: LangGraph raises `InvalidUpdateError` when two concurrent nodes
write the same un-reduced key. M1 has no fan-out yet, so these tests are the
only thing standing between a correct reducer today and a failure that
appears for the first time in M3 with nine specialists in flight.
"""

import operator
from typing import Annotated, get_args, get_origin, get_type_hints

import pytest

from app.graph.state import ResearchState, initial_state, keep_last, merge_dicts


class TestMergeDicts:
    def test_merges_disjoint_keys(self):
        """The realistic case: each parallel branch writes only its own task_id."""
        assert merge_dicts({"t1": "ok"}, {"t2": "failed"}) == {"t1": "ok", "t2": "failed"}

    def test_right_wins_on_conflict(self):
        assert merge_dicts({"t1": "running"}, {"t1": "ok"}) == {"t1": "ok"}

    def test_handles_none_on_either_side(self):
        assert merge_dicts(None, {"t1": "ok"}) == {"t1": "ok"}
        assert merge_dicts({"t1": "ok"}, None) == {"t1": "ok"}
        assert merge_dicts(None, None) == {}

    def test_does_not_mutate_inputs(self):
        left = {"t1": "ok"}
        merge_dicts(left, {"t2": "failed"})
        assert left == {"t1": "ok"}


class TestKeepLast:
    def test_prefers_right(self):
        assert keep_last(1, 2) == 2

    def test_falls_back_to_left_when_right_is_none(self):
        """A node returning nothing must not erase an existing value."""
        assert keep_last(5, None) == 5


class TestReducerCoverage:
    """
    Fields written concurrently MUST carry a reducer.

    Asserted structurally rather than by convention, so adding a
    parallel-written field without a reducer fails here instead of at
    runtime under fan-out.
    """

    CONCURRENTLY_WRITTEN = ["evidence_ids", "claim_ids", "task_status", "errors"]

    @pytest.mark.parametrize("field", CONCURRENTLY_WRITTEN)
    def test_concurrent_field_has_reducer(self, field):
        hints = get_type_hints(ResearchState, include_extras=True)
        assert get_origin(hints[field]) is Annotated, (
            f"'{field}' is written by parallel branches and MUST be Annotated "
            f"with a reducer, or LangGraph will raise InvalidUpdateError"
        )
        # Annotated[T, reducer] -- the reducer must be callable.
        assert callable(get_args(hints[field])[1])

    def test_list_fields_use_additive_reducer(self):
        """Accumulated lists must append, not overwrite -- otherwise evidence is lost."""
        hints = get_type_hints(ResearchState, include_extras=True)
        for field in ("evidence_ids", "claim_ids", "errors"):
            assert get_args(hints[field])[1] is operator.add


class TestInitialState:
    def test_counters_start_at_zero_not_none(self):
        """Loop bounds compare numerically; None would need guards everywhere."""
        state = initial_state("run_1", "NVDA")
        assert state["validation_attempts"] == 0
        assert state["replan_rounds"] == 0
        assert state["plan_revision"] == 0

    def test_accumulators_start_empty_not_none(self):
        state = initial_state("run_1", "NVDA")
        assert state["evidence_ids"] == []
        assert state["errors"] == []
        assert state["task_status"] == {}

    def test_preserves_raw_query_verbatim(self):
        """The user's exact input is retained for the audit trail."""
        state = initial_state("run_1", "  Apple Inc  ")
        assert state["raw_query"] == "  Apple Inc  "

    def test_starts_in_validating_status(self):
        assert initial_state("run_1", "NVDA")["status"] == "validating"
