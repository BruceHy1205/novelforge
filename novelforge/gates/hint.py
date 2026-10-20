"""G7 hint. The beat must land, stick, and match the strength budget.

`clues is None` skips the ledger check so older callers keep the short version.
"""

from __future__ import annotations

from novelforge.gates.reveal import is_after_hint_beat, is_hint_beat
from novelforge.roles.clues import accumulated_points
from novelforge.schema.canon import Canon
from novelforge.schema.clues import Clue
from novelforge.schema.gate import GateResult
from novelforge.schema.reader import CONFIDENCE_ORDER, ConfidenceBin


def _off_budget(on_beat: bool, hint_budget: str | None, best: int) -> bool:
    suspect = CONFIDENCE_ORDER.index("suspect")
    if not on_beat:
        return False
    if hint_budget == "light":
        return best >= suspect
    if hint_budget == "heavy":
        return best < suspect
    return False


def _best(levels: list[ConfidenceBin]) -> int:
    if not levels:
        return 0
    return max(CONFIDENCE_ORDER.index(level) for level in levels)


def check_hint(
    judged: dict[str, dict[str, ConfidenceBin]],
    canon: Canon,
    scene_id: str,
    scene_ids: list[str],
    clues: list[Clue] | None = None,
    hint_budget: str | None = None,
) -> GateResult:
    if not judged:
        return GateResult(gate_id="hint", passed=True, reasons=["no reader simulation"])
    missed = 0
    carried = 0
    overshot = 0
    unbudgeted = 0
    unplanted = 0
    for item in canon.reveal_plan:
        on_beat = is_hint_beat(item, scene_id, scene_ids)
        after = is_after_hint_beat(item, scene_id, scene_ids)
        if not on_beat and not after:
            continue
        levels = [confidence.get(item.secret_id, "none") for confidence in judged.values()]
        best = _best(levels)
        if best == CONFIDENCE_ORDER.index("certain"):
            overshot += 1
        elif best == 0 and on_beat:
            missed += 1
        elif best == 0 and after:
            carried += 1
        elif _off_budget(on_beat, hint_budget, best):
            unbudgeted += 1
        if (
            on_beat
            and clues is not None
            and accumulated_points(clues, item.secret_id, scene_id, scene_ids) == 0
        ):
            unplanted += 1
    reasons: list[str] = []
    if missed:
        reasons.append("hint beat produced no suspicion")
    if unplanted:
        reasons.append("hint beat has no clue")
    if carried:
        reasons.append("hint did not carry")
    if overshot:
        reasons.append("hint beat became certain")
    if unbudgeted:
        reasons.append("hint strength missed the budget")
    if not reasons:
        reasons.append("hint beat landed")
    failed = missed + carried + overshot + unbudgeted + unplanted
    return GateResult(
        gate_id="hint",
        passed=failed == 0,
        score=float(failed),
        reasons=reasons,
        details={"missed": str(missed), "overshot": str(overshot)},
    )
