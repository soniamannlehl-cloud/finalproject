"""
StateGraph assembly.

The topology is STATIC and stays static. Dynamic behavior comes from the
plan carried in state and dispatched via the `Send` API -- never from
rebuilding the graph per request, which would break checkpoint
compatibility across resumes and fragment traces.

M2 topology:

    START
      -> validate_company        (Checkpoint #1 interrupt lives here)
      -> planner                 selects industry playbook, emits task DAG
      -> director                decides the next execution layer
      -> [specialist_proxy] x N  parallel A2A dispatch via Send
      -> collect                 join barrier
      -> director                (loop while layers remain)
      -> END

The director <-> collect cycle is what executes a multi-layer plan: a plan
with statements -> ratios -> valuation passes through the Director three
times, dispatching one parallel batch each time.
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
from ..thesis.agent import thesis_node
from .nodes.validate import route_after_validation, validate_company_node
from .state import ResearchState

log = logging.getLogger(__name__)


def build_graph() -> StateGraph:
    """Assemble the workflow. Compiled separately so tests can inject a checkpointer."""
    graph = StateGraph(ResearchState)

    graph.add_node("validate_company", validate_company_node)
    graph.add_node("planner", planner_node)
    graph.add_node("director", director_node)
    graph.add_node("specialist_proxy", specialist_proxy_node)
    graph.add_node("collect", collect_node)
    graph.add_node("thesis", thesis_node)

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
            "done": END,             # M5 replaces this with the safety pipeline
        },
    )

    return graph


def compile_graph(checkpointer):
    """
    Compile with a checkpointer.

    Mandatory, not optional: without one, `interrupt()` cannot suspend and
    resume, so both HITL checkpoints would silently fail to pause.
    """
    return build_graph().compile(checkpointer=checkpointer)
