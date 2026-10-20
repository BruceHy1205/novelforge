"""Single-scene pipeline graph.

    plan_scene → build_view → write → pre_gates ─fail→ revise → pre_gates
                                          │pass
                                          ▼
                                    reader_sim → main_gates ─fail→ revise
                                                     │pass
                                                     ▼
                                               update_state → lock_scene → END

Revisions are capped at MAX_REVISIONS per plan; past that the scene is
replanned (→ build_view), and past MAX_REPLANS it is escalated for human
review. Only blocking gates count toward that. Advisory failures (length,
pace, style, hooks, reader taste) get ADVISORY_REVISIONS rewrites and then
the scene moves on with the advice on record. Nodes are plain functions
`state -> partial update`; the graph only routes, so every node can be
unit-tested on its own.
"""

from __future__ import annotations

import operator
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Annotated, Any, Literal, TypedDict

from novelforge.schema.gate import GateResult
from novelforge.schema.reader import ReaderReport
from novelforge.schema.scene import LockedScene, SceneCard, WriterView
from novelforge.schema.state import BookState
from novelforge.view.filter import build_writer_view

MAX_REVISIONS = 2
MAX_REPLANS = 1
ADVISORY_REVISIONS = 1
RECURSION_LIMIT = 100


class SceneState(TypedDict, total=False):
    book: BookState
    card: SceneCard
    view: WriterView
    draft: str
    critic_notes: list[str]
    theme_hit: bool
    theme_note: str
    pre_gate_results: list[GateResult]
    reader_reports: list[ReaderReport]
    judged: dict[str, dict[str, str]]
    scene_ids: list[str]
    main_gate_results: list[GateResult]
    revision_count: int
    replan_count: int
    locked: LockedScene
    status: Literal["running", "locked", "escalated"]
    path: Annotated[list[str], operator.add]


NodeFn = Callable[[SceneState], dict[str, Any]]


def _not_implemented(name: str) -> NodeFn:
    def node(_state: SceneState) -> dict[str, Any]:
        raise NotImplementedError(f"scene node '{name}' is not implemented yet")

    return node


def default_build_view(state: SceneState) -> dict[str, Any]:
    return {"view": build_writer_view(state["book"], state["card"])}


def default_lock_scene(state: SceneState) -> dict[str, Any]:
    locked = LockedScene.lock(state["card"].scene_id, state["draft"])
    book = state["book"].model_copy(
        update={"locked_scenes": [*state["book"].locked_scenes, locked]}
    )
    return {"locked": locked, "book": book}


@dataclass(frozen=True)
class SceneNodes:
    plan_scene: NodeFn = field(default_factory=lambda: _not_implemented("plan_scene"))
    build_view: NodeFn = default_build_view
    write: NodeFn = field(default_factory=lambda: _not_implemented("write"))
    pre_gates: NodeFn = field(default_factory=lambda: _not_implemented("pre_gates"))
    revise: NodeFn = field(default_factory=lambda: _not_implemented("revise"))
    reader_sim: NodeFn = field(default_factory=lambda: _not_implemented("reader_sim"))
    main_gates: NodeFn = field(default_factory=lambda: _not_implemented("main_gates"))
    update_state: NodeFn = field(default_factory=lambda: _not_implemented("update_state"))
    replan_scene: NodeFn = field(default_factory=lambda: _not_implemented("replan_scene"))
    lock_scene: NodeFn = default_lock_scene


def gates_passed(results: list[GateResult] | None) -> bool:
    return all(result.passed for result in results or [])


def blocking_passed(results: list[GateResult] | None) -> bool:
    return all(result.passed or not result.blocking for result in results or [])


def _route_after(results_key: str, on_pass: str) -> Callable[[SceneState], str]:
    def route(state: SceneState) -> str:
        results = state.get(results_key)
        if gates_passed(results):  # type: ignore[arg-type]
            return on_pass
        if blocking_passed(results):  # type: ignore[arg-type]
            if state.get("revision_count", 0) < ADVISORY_REVISIONS:
                return "revise"
            return on_pass
        if state.get("revision_count", 0) < MAX_REVISIONS:
            return "revise"
        if state.get("replan_count", 0) < MAX_REPLANS:
            return "replan_scene"
        return "escalate"

    return route


def _traced(name: str, fn: NodeFn, bookkeeping: NodeFn | None = None) -> NodeFn:
    def node(state: SceneState) -> dict[str, Any]:
        update = dict(fn(state) or {})
        if bookkeeping is not None:
            update.update(bookkeeping(state))
        update["path"] = [name]
        return update

    return node


def _start(_state: SceneState) -> dict[str, Any]:
    return {"status": "running", "revision_count": 0, "replan_count": 0}


def _count_revision(state: SceneState) -> dict[str, Any]:
    return {"revision_count": state.get("revision_count", 0) + 1}


def _count_replan(state: SceneState) -> dict[str, Any]:
    return {"replan_count": state.get("replan_count", 0) + 1, "revision_count": 0}


def _escalate(_state: SceneState) -> dict[str, Any]:
    return {"status": "escalated"}


def _mark_locked(_state: SceneState) -> dict[str, Any]:
    return {"status": "locked"}


def build_scene_graph(nodes: SceneNodes | None = None, checkpointer: Any | None = None) -> Any:
    from langgraph.graph import END, StateGraph

    nodes = nodes or SceneNodes()
    graph = StateGraph(SceneState)
    graph.add_node("plan_scene", _traced("plan_scene", nodes.plan_scene, _start))
    graph.add_node("build_view", _traced("build_view", nodes.build_view))
    graph.add_node("write", _traced("write", nodes.write))
    graph.add_node("pre_gates", _traced("pre_gates", nodes.pre_gates))
    graph.add_node("revise", _traced("revise", nodes.revise, _count_revision))
    graph.add_node("reader_sim", _traced("reader_sim", nodes.reader_sim))
    graph.add_node("main_gates", _traced("main_gates", nodes.main_gates))
    graph.add_node("update_state", _traced("update_state", nodes.update_state))
    graph.add_node("replan_scene", _traced("replan_scene", nodes.replan_scene, _count_replan))
    graph.add_node("lock_scene", _traced("lock_scene", nodes.lock_scene, _mark_locked))
    graph.add_node("escalate", _traced("escalate", lambda _s: {}, _escalate))

    graph.set_entry_point("plan_scene")
    graph.add_edge("plan_scene", "build_view")
    graph.add_edge("build_view", "write")
    graph.add_edge("write", "pre_gates")
    graph.add_conditional_edges(
        "pre_gates",
        _route_after("pre_gate_results", "reader_sim"),
        ["reader_sim", "revise", "replan_scene", "escalate"],
    )
    graph.add_edge("revise", "pre_gates")
    graph.add_edge("reader_sim", "main_gates")
    graph.add_conditional_edges(
        "main_gates",
        _route_after("main_gate_results", "update_state"),
        ["update_state", "revise", "replan_scene", "escalate"],
    )
    graph.add_edge("replan_scene", "build_view")
    graph.add_edge("update_state", "lock_scene")
    graph.add_edge("lock_scene", END)
    graph.add_edge("escalate", END)
    compiled = graph.compile(checkpointer=checkpointer)
    return compiled.with_config(recursion_limit=RECURSION_LIMIT)


def sqlite_saver(path: str) -> Any:
    """Open a SqliteSaver. Close `saver.conn` when finished, or use sqlite_checkpointer."""

    import sqlite3

    from langgraph.checkpoint.serde.jsonplus import JsonPlusSerializer
    from langgraph.checkpoint.sqlite import SqliteSaver

    from novelforge.graph.checkpoint import ALLOWED_MSGPACK_MODULES

    serde = JsonPlusSerializer(allowed_msgpack_modules=ALLOWED_MSGPACK_MODULES)
    connection = sqlite3.connect(path, check_same_thread=False)
    return SqliteSaver(connection, serde=serde)
