"""Routing tests for the single-scene graph. Nodes are fakes; only edges are under test."""

from __future__ import annotations

from collections.abc import Iterator
from typing import Any

import pytest

from novelforge.graph.scene_graph import MAX_REPLANS, MAX_REVISIONS, SceneNodes, build_scene_graph
from novelforge.schema.canon import Canon, Secret
from novelforge.schema.gate import GateResult
from novelforge.schema.scene import SceneCard
from novelforge.schema.state import BookState
from novelforge.view.filter import SecretLeakError

PASS = [GateResult(gate_id="g", passed=True)]
FAIL = [GateResult(gate_id="g", passed=False)]


def _gate(outcomes: list[bool], key: str) -> Any:
    sequence: Iterator[bool] = iter(outcomes)

    def node(_state: Any) -> dict[str, Any]:
        return {key: PASS if next(sequence, True) else FAIL}

    return node


def _nodes(pre: list[bool], main: list[bool], **overrides: Any) -> SceneNodes:
    base: dict[str, Any] = {
        "plan_scene": lambda s: {"card": s.get("card") or SceneCard(scene_id="sc-01")},
        "write": lambda _s: {"draft": "draft"},
        "pre_gates": _gate(pre, "pre_gate_results"),
        "revise": lambda s: {"draft": s["draft"] + "+"},
        "reader_sim": lambda _s: {"reader_reports": []},
        "main_gates": _gate(main, "main_gate_results"),
        "update_state": lambda _s: {},
        "replan_scene": lambda _s: {},
    }
    base.update(overrides)
    return SceneNodes(**base)


def _run(nodes: SceneNodes, book: BookState | None = None) -> dict[str, Any]:
    return build_scene_graph(nodes).invoke({"book": book or BookState(), "path": []})


def test_happy_path_locks_scene() -> None:
    result = _run(_nodes(pre=[True], main=[True]))
    assert result["path"] == [
        "plan_scene",
        "build_view",
        "write",
        "pre_gates",
        "reader_sim",
        "main_gates",
        "update_state",
        "lock_scene",
    ]
    assert result["status"] == "locked"
    assert result["locked"].text == "draft"
    assert result["book"].locked_scenes[-1].scene_id == "sc-01"


def test_pre_gate_failure_revises_then_rechecks() -> None:
    result = _run(_nodes(pre=[False, True], main=[True]))
    assert result["path"][3:6] == ["pre_gates", "revise", "pre_gates"]
    assert result["locked"].text == "draft+"
    assert result["status"] == "locked"


def test_main_gate_failure_revises_through_pre_gates() -> None:
    result = _run(_nodes(pre=[True, True], main=[False, True]))
    assert result["path"][5:10] == ["main_gates", "revise", "pre_gates", "reader_sim", "main_gates"]
    assert result["status"] == "locked"


def test_exhausted_revisions_replan_then_escalate() -> None:
    result = _run(_nodes(pre=[False] * 20, main=[]))
    path = result["path"]
    assert path.count("revise") == MAX_REVISIONS * (MAX_REPLANS + 1)
    assert path.count("replan_scene") == MAX_REPLANS
    assert path[-1] == "escalate"
    assert result["status"] == "escalated"
    assert "lock_scene" not in path


def test_advisory_failures_get_one_rewrite_then_lock() -> None:
    advice = [GateResult(gate_id="length", passed=False, blocking=False)]
    nodes = _nodes(
        pre=[True],
        main=[True],
        pre_gates=lambda _s: {"pre_gate_results": advice},
        main_gates=lambda _s: {"main_gate_results": advice},
    )
    result = _run(nodes)
    assert result["status"] == "locked"
    assert result["path"].count("revise") == 1
    assert "replan_scene" not in result["path"]


def test_blocking_failure_mixed_with_advice_still_escalates() -> None:
    mixed = [
        GateResult(gate_id="length", passed=False, blocking=False),
        GateResult(gate_id="literal", passed=False),
    ]
    nodes = _nodes(pre=[], main=[], pre_gates=lambda _s: {"pre_gate_results": mixed})
    result = _run(nodes)
    assert result["status"] == "escalated"


def test_replan_resets_revision_budget() -> None:
    result = _run(_nodes(pre=[False] * MAX_REVISIONS + [False, True], main=[True]))
    path = result["path"]
    assert path.count("replan_scene") == 1
    replan_at = path.index("replan_scene")
    assert path[replan_at + 1 : replan_at + 3] == ["build_view", "write"]
    assert result["status"] == "locked"


def test_default_build_view_enforces_isolation() -> None:
    book = BookState(canon=Canon(secrets=[Secret(id="S-1", title="t", text="the twin")]))
    card = SceneCard(scene_id="sc-01", directives=["mention the twin"])
    nodes = _nodes(pre=[True], main=[True], plan_scene=lambda _s: {"card": card})
    with pytest.raises(SecretLeakError):
        _run(nodes, book)


def test_unimplemented_nodes_fail_loudly() -> None:
    with pytest.raises(NotImplementedError):
        build_scene_graph().invoke({"book": BookState(), "path": []})
