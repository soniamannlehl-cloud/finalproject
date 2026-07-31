"""
StateGraph assembly.

The topology here is STATIC and stays static. Dynamic behavior comes from
the plan carried in state and dispatched via the `Send` API (M2+), never
from rebuilding the graph per request -- a per-request graph would break
checkpoint compatibility across resumes and fragment traces.

M1 topology:

    START -> validate_company -> END

`validate_company` contains the Checkpoint #1 interrupt. In M2, its
"validated" branch routes to the Planner instead of END.
"""

import logging

from langgraph.graph import END, START, StateGraph

from .nodes.validate import route_after_validation, validate_company_node
from .state import ResearchState

log = logging.getLogger(__name__)


def build_graph() -> StateGraph:
    """Assemble the workflow. Compiled separately so tests can supply their own checkpointer."""
    graph = StateGraph(ResearchState)

    graph.add_node("validate_company", validate_company_node)

    graph.add_edge(START, "validate_company")
    graph.add_conditional_edges(
        "validate_company",
        route_after_validation,
        {
            # M2 replaces this target with "planner".
            "validated": END,
            "stop": END,
        },
    )

    return graph


def compile_graph(checkpointer):
    """
    Compile with a checkpointer.

    A checkpointer is mandatory rather than optional: without one,
    `interrupt()` cannot suspend and resume, so both HITL checkpoints would
    silently fail to pause.
    """
    return build_graph().compile(checkpointer=checkpointer)
