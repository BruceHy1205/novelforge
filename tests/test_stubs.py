from __future__ import annotations

import pytest

from novelforge.eval.metrics import bin_confidence
from novelforge.gates.length import check_length
from novelforge.gates.literal import check_literal, embed_for_leak_screen
from novelforge.graph.book_graph import build_book_graph
from novelforge.pacing.curve import tension_curve


def test_literal_gate_exact_match() -> None:
    leaked = check_literal("the butler did it TOKEN", ["TOKEN"])
    clean = check_literal("the tide came in", ["TOKEN"])
    assert leaked.passed is False
    assert clean.passed is True


def test_embed_stub_is_not_implemented() -> None:
    with pytest.raises(NotImplementedError):
        embed_for_leak_screen(["x"])


def test_length_gate() -> None:
    result = check_length("word " * 100, target_words=100, tolerance=0.1)
    assert result.passed is True


def test_tension_curve_rises_and_breathes() -> None:
    assert tension_curve(0) == []
    curve = tension_curve(8)
    assert len(curve) == 8
    assert curve[0] < curve[-1]
    assert any(curve[index] < curve[index - 1] - 0.1 for index in range(1, len(curve)))


def test_bin_confidence() -> None:
    assert bin_confidence("hint") == "hint"
    assert bin_confidence(0.05) == "none"
    assert bin_confidence(0.9) == "certain"


def test_book_graph_walks_every_scene() -> None:
    graph = build_book_graph()
    result = graph.invoke({"project": "demo", "cursor": 0, "card_count": 2})
    assert result["project"] == "demo"
    assert result["cursor"] == 2
    assert result["status"] == "done"
