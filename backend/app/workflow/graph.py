from typing import Optional

from langgraph.graph import StateGraph, END
from app.workflow.state import InvestigationState
from app.workflow.nodes import (
    receive_incident,
    validate_incident,
    prepare_investigation,
    mark_ready,
)


def build_investigation_graph(checkpointer=None):
    """Build and compile the investigation StateGraph.

    Parameters
    ----------
    checkpointer:
        An optional LangGraph checkpointer (e.g. ``PostgresSaver``) that
        enables persistent state snapshots.  When ``None`` the graph runs
        without persistence (in-memory only).
    """
    graph = StateGraph(InvestigationState)

    graph.add_node("receive_incident", receive_incident)
    graph.add_node("validate_incident", validate_incident)
    graph.add_node("prepare_investigation", prepare_investigation)
    graph.add_node("mark_ready", mark_ready)

    graph.set_entry_point("receive_incident")

    graph.add_conditional_edges(
        "receive_incident",
        lambda state: "validate_incident" if state.get("status") != "failed" else END,
        {"validate_incident": "validate_incident", END: END},
    )

    graph.add_conditional_edges(
        "validate_incident",
        lambda state: "prepare_investigation" if state.get("status") != "failed" else END,
        {"prepare_investigation": "prepare_investigation", END: END},
    )

    graph.add_conditional_edges(
        "prepare_investigation",
        lambda state: "mark_ready" if state.get("status") != "failed" else END,
        {"mark_ready": "mark_ready", END: END},
    )

    graph.add_edge("mark_ready", END)

    return graph.compile(checkpointer=checkpointer)
