"""Directive gate. A cause, or a line the reader can guess from, does not reach the writer."""

from __future__ import annotations

from typing import Any

from novelforge.roles.behavior import CAUSAL_MARKERS
from novelforge.roles.directives import leaking_secret_ids, visible_lines
from novelforge.roles.guess_judge import GuessJudge
from novelforge.schema.canon import Canon
from novelforge.schema.gate import GateResult
from novelforge.schema.reader import Persona
from novelforge.schema.scene import SceneCard


def check_directives(
    card: SceneCard,
    canon: Canon,
    personas: list[Persona],
    client: Any,
    judge: GuessJudge,
    *,
    leak: bool = True,
) -> GateResult:
    if any(marker in line for line in card.directives for marker in CAUSAL_MARKERS):
        return GateResult(
            gate_id="directive",
            passed=False,
            reasons=["directive states a cause"],
        )
    if not leak:
        return GateResult(gate_id="directive", passed=True, reasons=["directives stay behavioral"])
    if leaking_secret_ids(
        visible_lines(card), canon, personas, client, judge, allowed=set(card.must_reveal)
    ):
        return GateResult(gate_id="directive", passed=False, reasons=["directive leak"])
    return GateResult(gate_id="directive", passed=True, reasons=["directives stay behavioral"])
