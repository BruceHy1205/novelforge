"""G5 inferred leak and G6 reveal beyond the plan. Reasons do not quote secrets."""

from __future__ import annotations

from novelforge.gates.reveal import allowed_confidence, over_cap, plan_for
from novelforge.roles.clues import accumulated_points, cap_from_points
from novelforge.schema.canon import Canon
from novelforge.schema.clues import Clue
from novelforge.schema.gate import GateResult
from novelforge.schema.reader import CONFIDENCE_ORDER, ConfidenceBin


def _lower(left: ConfidenceBin, right: ConfidenceBin) -> ConfidenceBin:
    if CONFIDENCE_ORDER.index(left) <= CONFIDENCE_ORDER.index(right):
        return left
    return right


def inference_cap(
    canon: Canon,
    secret_id: str,
    scene_id: str,
    scene_ids: list[str],
    clues: list[Clue] | None = None,
) -> ConfidenceBin:
    """Plan cap, tightened by public clues planted so far.

    No clues keeps the P2 plan cap. A reveal beat still allows certainty.
    Otherwise the reader may not get ahead of either the plan or the ledger.
    """

    plan_cap = allowed_confidence(plan_for(canon, secret_id), scene_id, scene_ids)
    points = accumulated_points(clues or [], secret_id, scene_id, scene_ids)
    if points <= 0 or plan_cap == "certain":
        return plan_cap
    return _lower(plan_cap, cap_from_points(points))


def check_inference(
    judged: dict[str, dict[str, ConfidenceBin]],
    canon: Canon,
    scene_id: str,
    scene_ids: list[str],
    clues: list[Clue] | None = None,
    *,
    tolerance: int = 0,
) -> GateResult:
    """Fail when any persona is more sure than the clue ledger and the plan allow.

    `tolerance` lets a reader run that many bins ahead, short of certainty.
    A mystery reader who suspects the right thing one step early is engaged,
    not spoiled; certainty before the reveal always fails.
    """

    leaks = 0
    ahead = 0
    for confidence in judged.values():
        for secret_id, actual in confidence.items():
            cap = inference_cap(canon, secret_id, scene_id, scene_ids, clues)
            if not over_cap(actual, cap):
                continue
            gap = CONFIDENCE_ORDER.index(actual) - CONFIDENCE_ORDER.index(cap)
            if gap > tolerance or actual == "certain":
                leaks += 1
            else:
                ahead += 1
    if leaks:
        reasons = ["reader is ahead of the reveal plan"]
    elif ahead:
        reasons = [f"confidence within tolerance ({ahead} one step ahead)"]
    else:
        reasons = ["confidence within plan"]
    return GateResult(
        gate_id="inference",
        passed=leaks == 0,
        score=float(leaks),
        reasons=reasons,
        details={"leaks": str(leaks), "ahead": str(ahead)},
    )


def check_reveal_authority(
    judged: dict[str, dict[str, ConfidenceBin]],
    canon: Canon,
    scene_id: str,
    scene_ids: list[str],
) -> GateResult:
    """Fail when a persona is certain about a secret this scene may not reveal."""

    leaks = 0
    for confidence in judged.values():
        for secret_id, actual in confidence.items():
            cap = allowed_confidence(plan_for(canon, secret_id), scene_id, scene_ids)
            if actual == "certain" and cap != "certain":
                leaks += 1
    return GateResult(
        gate_id="reveal",
        passed=leaks == 0,
        score=float(leaks),
        reasons=["unplanned reveal"] if leaks else ["no unplanned reveal"],
        details={"leaks": str(leaks)},
    )
