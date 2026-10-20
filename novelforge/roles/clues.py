"""Clue ledger. Public clues spend a strength budget; author-only clues do not count."""

from __future__ import annotations

from novelforge.schema.canon import Canon
from novelforge.schema.clues import Clue, ClueStrength
from novelforge.schema.reader import ConfidenceBin
from novelforge.schema.scene import SceneCard

STRENGTH_POINTS: dict[ClueStrength, int] = {"trace": 1, "notice": 2, "pointer": 3}
METHOD_BUDGET: dict[str, int] = {"withhold": 1, "hint": 3, "reveal": 5}


def strength_name(hint_budget: object) -> ClueStrength:
    if hint_budget == "moderate":
        return "notice"
    if hint_budget == "heavy":
        return "pointer"
    return "trace"


def cap_from_points(points: int) -> ConfidenceBin:
    if points <= 0:
        return "none"
    if points == 1:
        return "hint"
    if points <= 3:
        return "suspect"
    return "certain"


def _scene_index(scene_id: str | None, scene_ids: list[str]) -> int | None:
    if scene_id is None or scene_id not in scene_ids:
        return None
    return scene_ids.index(scene_id)


def accumulated_points(
    clues: list[Clue], secret_id: str, scene_id: str, scene_ids: list[str]
) -> int:
    """Public strength planted at or before this scene. Author-only clues add nothing."""

    here = _scene_index(scene_id, scene_ids)
    total = 0
    for clue in clues:
        if clue.visibility != "public" or clue.secret_id != secret_id:
            continue
        planted = _scene_index(clue.planted_in, scene_ids)
        if planted is None:
            if clue.planted_in == scene_id:
                total += STRENGTH_POINTS[clue.strength]
            continue
        if here is None or planted <= here:
            total += STRENGTH_POINTS[clue.strength]
    return total


def _mentions(card: SceneCard, secret_id: str, canon: Canon) -> bool:
    if secret_id in card.must_reveal or secret_id in card.must_withhold:
        return True
    return any(
        item.secret_id == secret_id and item.earliest_scene_id == card.scene_id
        for item in canon.reveal_plan
    )


def _method(canon: Canon, secret_id: str) -> str:
    for item in canon.reveal_plan:
        if item.secret_id == secret_id:
            return item.method
    return "withhold"


def build_clues(cards: list[SceneCard], canon: Canon) -> list[Clue]:
    """One public clue per scene that touches a secret, until the budget is spent."""

    spent: dict[str, int] = {}
    clues: list[Clue] = []
    for card in cards:
        if not card.directives:
            continue
        for secret in canon.secrets:
            if not _mentions(card, secret.id, canon):
                continue
            method = _method(canon, secret.id)
            budget = METHOD_BUDGET[method]
            have = spent.get(secret.id, 0)
            strength = strength_name(card.hint_budget)
            add = STRENGTH_POINTS[strength]
            if have + add > budget:
                if have + STRENGTH_POINTS["trace"] <= budget:
                    strength = "trace"
                    add = STRENGTH_POINTS["trace"]
                else:
                    continue
            spent[secret.id] = have + add
            clues.append(
                Clue(
                    id=f"clue-{card.scene_id}-{secret.id}",
                    text=card.directives[0],
                    secret_id=secret.id,
                    visibility="public",
                    planted_in=card.scene_id,
                    strength=strength,
                )
            )
    return clues
