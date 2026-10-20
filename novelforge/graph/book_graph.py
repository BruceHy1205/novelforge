"""Book graph: write scene cards in order, then stop. The cursor is the checkpoint."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any, TypedDict


class BookGraphState(TypedDict, total=False):
    cursor: int
    card_count: int
    project: str
    status: str


WriteOne = Callable[[BookGraphState], dict[str, Any]]


def build_book_graph(write_one: WriteOne | None = None, checkpointer: Any | None = None) -> Any:
    from langgraph.graph import END, StateGraph

    def write_scene(state: BookGraphState) -> dict[str, Any]:
        extra = write_one(state) if write_one is not None else {}
        cursor = state.get("cursor", 0) + 1
        finished = cursor >= state.get("card_count", 0)
        return {
            "cursor": cursor,
            "status": "done" if finished else "running",
            **(extra or {}),
        }

    def route(state: BookGraphState) -> str:
        if state.get("cursor", 0) >= state.get("card_count", 0):
            return END
        return "write_scene"

    graph = StateGraph(BookGraphState)
    graph.add_node("route", lambda state: state)
    graph.add_node("write_scene", write_scene)
    graph.set_entry_point("route")
    graph.add_conditional_edges("route", route, ["write_scene", END])
    graph.add_edge("write_scene", "route")
    compiled = graph.compile(checkpointer=checkpointer)
    return compiled.with_config(recursion_limit=80)
