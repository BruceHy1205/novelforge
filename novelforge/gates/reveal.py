"""How much a reader may know at a scene, according to the reveal plan."""

from __future__ import annotations

from novelforge.schema.canon import Canon, RevealPlanItem
from novelforge.schema.reader import CONFIDENCE_ORDER, ConfidenceBin

CAP_BY_METHOD: dict[str, ConfidenceBin] = {
    "withhold": "none",
    "hint": "hint",
    "reveal": "certain",
}


def _at_or_after(scene_id: str, earliest: str | None, scene_ids: list[str]) -> bool:
    if earliest is None:
        return True
    if scene_ids and earliest in scene_ids and scene_id in scene_ids:
        return scene_ids.index(scene_id) >= scene_ids.index(earliest)
    return scene_id == earliest


def plan_for(canon: Canon, secret_id: str) -> RevealPlanItem | None:
    return next((item for item in canon.reveal_plan if item.secret_id == secret_id), None)


def allowed_confidence(
    item: RevealPlanItem | None, scene_id: str, scene_ids: list[str]
) -> ConfidenceBin:
    if item is None:
        return "none"
    if not _at_or_after(scene_id, item.earliest_scene_id, scene_ids):
        return "none"
    return CAP_BY_METHOD[item.method]


def over_cap(actual: ConfidenceBin, cap: ConfidenceBin) -> bool:
    return CONFIDENCE_ORDER.index(actual) > CONFIDENCE_ORDER.index(cap)


def is_hint_beat(item: RevealPlanItem, scene_id: str, scene_ids: list[str]) -> bool:
    if item.method != "hint" or item.earliest_scene_id is None:
        return False
    if scene_ids and item.earliest_scene_id in scene_ids and scene_id in scene_ids:
        return scene_ids.index(scene_id) == scene_ids.index(item.earliest_scene_id)
    return scene_id == item.earliest_scene_id


def is_after_hint_beat(item: RevealPlanItem, scene_id: str, scene_ids: list[str]) -> bool:
    if item.method != "hint" or item.earliest_scene_id is None:
        return False
    if scene_ids and item.earliest_scene_id in scene_ids and scene_id in scene_ids:
        return scene_ids.index(scene_id) > scene_ids.index(item.earliest_scene_id)
    return False
