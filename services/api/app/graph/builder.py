"""
StateGraph assembly.

The topology is STATIC and stays static. Dynamic behavior comes from the
plan carried in state and dispatched via the `Send` API -- never from
rebuilding the graph per request, which would break checkpoint
compatibility across resumes and fragment traces.

Full topology:

    START
      -> validate_company        (HITL #1 interrupt)
      -> planner                 industry playbook -> task DAG
      -> director                next execution layer
      -> [specialist_proxy] x N  parallel A2A dispatch via Send
      -> collect                 join barrier
      -> thesis                  living thesis update
      -> director                (loop while layers remain)
      -> safety                  L1/L2 verification
      -> committee               CrewAI Bull/Bear/CIO via A2A
      -> synthesizer             deterministic policy gate
      -> report_generator        PDF-ready report for committee review
      -> hitl_2                  HITL #2 interrupt (human reviews report + recommendation)
      -> planner                 (replan loop on request_analysis)
      -> END
"""

import logging

from langgraph.graph import END, START, StateGraph

from ..director.director import (
    collect_node,
    director_node,
    dispatch_edge,
    route_after_collect,
    specialist_proxy_node,
)
from ..planning.planner import planner_node
from ..safety.pipeline import safety_node
from ..thesis.agent import thesis_node
from .nodes.committee import committee_node
from .nodes.hitl_2 import hitl_2_node, route_after_hitl_2
from .nodes.report import report_generator_node
from .nodes.synthesizer import synthesizer_node
from .nodes.validate import route_after_validation, validate_company_node
from .state import ResearchState

log = logging.getLogger(__name__)


def route_after_safety(state: dict) -> str:
    """Skip committee only when the safety pipeline itself crashed."""
    if state.get("status") == "safety_failed":
        return "failed"
    return "continue"


def build_graph() -> StateGraph:
    """Assemble the workflow. Compiled separately so tests can inject a checkpointer."""
    graph = StateGraph(ResearchState)

    graph.add_node("validate_company", validate_company_node)
    graph.add_node("planner", planner_node)
    graph.add_node("director", director_node)
    graph.add_node("specialist_proxy", specialist_proxy_node)
    graph.add_node("collect", collect_node)
    graph.add_node("thesis", thesis_node)
    graph.add_node("safety", safety_node)
    graph.add_node("committee", committee_node)
    graph.add_node("synthesizer", synthesizer_node)
    graph.add_node("hitl_2", hitl_2_node)
    graph.add_node("report_generator", report_generator_node)

    graph.add_edge(START, "validate_company")

    # Only a human-confirmed company proceeds to cost money on research.
    graph.add_conditional_edges(
        "validate_company",
        route_after_validation,
        {"validated": "planner", "stop": END},
    )

    graph.add_edge("planner", "director")

    # The dynamic fan-out. `dispatch_edge` returns a list of Send objects --
    # one per ready task -- so N is decided at runtime from the plan while
    # the graph itself stays fixed at five nodes.
    graph.add_conditional_edges(
        "director",
        dispatch_edge,
        ["specialist_proxy", "collect"],
    )

    # All parallel branches converge here before the next layer is planned.
    graph.add_edge("specialist_proxy", "collect")

    # Thesis updates after EVERY batch, not once at the end -- that is what
    # makes it a living thesis rather than a final summary.
    graph.add_edge("collect", "thesis")

    graph.add_conditional_edges(
        "thesis",
        route_after_collect,
        {
            "continue": "director",  # more layers remain
            "done": "safety",        # research complete -> verify before concluding
        },
    )

    graph.add_conditional_edges(
        "safety",
        route_after_safety,
        {"continue": "committee", "failed": END},
    )

    graph.add_edge("committee", "synthesizer")
    graph.add_edge("synthesizer", "report_generator")
    graph.add_edge("report_generator", "hitl_2")

    graph.add_conditional_edges(
        "hitl_2",
        route_after_hitl_2,
        {"replan": "planner", "complete": END},
    )

    return graph


def compile_graph(checkpointer):
    """
    Compile with a checkpointer.

    Mandatory, not optional: without one, `interrupt()` cannot suspend and
    resume, so both HITL checkpoints would silently fail to pause.
    """
    return build_graph().compile(checkpointer=checkpointer)
