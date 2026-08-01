"""Tests for graph topology after M6/M7 integration."""

from app.graph.builder import build_graph, route_after_safety


class TestGraphTopology:
    def test_graph_has_committee_and_hitl_nodes(self):
        graph = build_graph()
        node_names = set(graph.nodes.keys())
        assert "committee" in node_names
        assert "synthesizer" in node_names
        assert "hitl_2" in node_names
        assert "report_generator" in node_names

    def test_safety_routes_to_committee_on_success(self):
        assert route_after_safety({"status": "safety_passed"}) == "continue"

    def test_safety_routes_to_end_on_pipeline_failure(self):
        assert route_after_safety({"status": "safety_failed"}) == "failed"
