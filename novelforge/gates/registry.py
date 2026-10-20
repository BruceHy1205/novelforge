"""Every gate behind one signature, so a genre can pick and tier them.

`pre` gates run before the reader simulator and must be cheap. A pre gate
with a `deferred` check runs its cheap form first; the expensive form runs
only once every blocking pre gate passes, and its result goes last.
A check may return None when it does not apply to this chapter.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any, Literal

from novelforge.schema.gate import GateResult
from novelforge.schema.reader import Persona, ReaderReport
from novelforge.schema.scene import SceneCard
from novelforge.schema.state import BookState

Stage = Literal["pre", "main"]


@dataclass
class GateContext:
    book: BookState
    card: SceneCard
    draft: str
    scene_ids: list[str]
    personas: list[Persona]
    client: Any
    judge: Any
    reports: list[ReaderReport] = field(default_factory=list)
    judged: dict[str, dict[str, str]] = field(default_factory=dict)
    wants: list[str] = field(default_factory=list)
    previous_questions: list[str] = field(default_factory=list)
    theme_hit: bool | None = None
    revision_count: int = 0
    inference_tolerance: int = 1


Check = Callable[[GateContext], GateResult | None]


@dataclass(frozen=True)
class GateSpec:
    id: str
    stage: Stage
    check: Check
    deferred: Check | None = None
    # Which prompt to edit when this gate keeps failing (`novelforge gates`).
    prompt: str = "writer"


GATES: dict[str, GateSpec] = {}


def register_gate(spec: GateSpec) -> GateSpec:
    if spec.id in GATES and GATES[spec.id] != spec:
        raise ValueError(f"gate {spec.id} is already registered")
    GATES[spec.id] = spec
    return spec


def gate(gate_id: str) -> GateSpec:
    _load_builtin()
    try:
        return GATES[gate_id]
    except KeyError as exc:
        raise KeyError(f"unknown gate {gate_id}") from exc


def run_stage(
    stage: Stage,
    tiers: tuple[tuple[str, str], ...],
    context: GateContext,
) -> list[GateResult]:
    specs = [(gate(gate_id), tier) for gate_id, tier in tiers]
    for spec, _ in specs:
        if spec.stage != stage:
            raise ValueError(f"gate {spec.id} runs in {spec.stage}, not {stage}")
    results = _run([(spec.check, tier) for spec, tier in specs], context)
    deferred = [(spec, tier) for spec, tier in specs if spec.deferred is not None]
    if deferred and all(result.passed or not result.blocking for result in results):
        ids = {spec.id for spec, _ in deferred}
        results = [result for result in results if result.gate_id not in ids]
        results.extend(_run([(spec.deferred, tier) for spec, tier in deferred], context))
    return results


def _run(checks: list[tuple[Check | None, str]], context: GateContext) -> list[GateResult]:
    results: list[GateResult] = []
    for check, tier in checks:
        if check is None:
            continue
        result = check(context)
        if result is None:
            continue
        results.append(result if tier == "blocking" else result.advisory())
    return results


_loaded = False


def _load_builtin() -> None:
    global _loaded
    if not _loaded:
        _loaded = True
        import novelforge.gates.builtin  # noqa: F401
