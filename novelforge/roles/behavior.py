"""Behavior directives: visible action, no cause, no identity.

The planner may write a reason. This layer cuts it off before the writer
sees the line. The leak check lives in the scene gates.
"""

from __future__ import annotations

from novelforge.schema.canon import Canon
from novelforge.schema.scene import SceneCard

CAUSAL_MARKERS: tuple[str, ...] = (
    "因为",
    "所以",
    "其实",
    "原来",
    "为了",
    "原因是",
    "身份是",
    "动机是",
)

HINT_ANOMALY = "安排一个看得见的异常，不要解释。"


def behavior_lines(lines: list[str]) -> list[str]:
    """Keep the visible action. Drop a line that is only a cause."""

    kept: list[str] = []
    for line in lines:
        action = _action_only(line)
        if action and action not in kept:
            kept.append(action)
    return kept


def _action_only(line: str) -> str:
    text = line.strip()
    if not text:
        return ""
    for marker in CAUSAL_MARKERS:
        if marker in text:
            text = text.split(marker, 1)[0]
    return text.strip(" ，,。;；")


def needs_hint_anomaly(card: SceneCard, canon: Canon) -> bool:
    return any(
        item.method == "hint" and item.earliest_scene_id == card.scene_id
        for item in canon.reveal_plan
    )


def apply_behavior(card: SceneCard, canon: Canon) -> SceneCard:
    """Derive the writer-facing directives for one card."""

    lines = behavior_lines(card.directives)
    plants = behavior_lines(card.plants)
    if not lines and not plants and needs_hint_anomaly(card, canon):
        lines = [HINT_ANOMALY]
    update: dict[str, object] = {
        "directives": lines,
        "plants": plants,
        "misdirection": behavior_lines(card.misdirection),
    }
    beats = {name: behavior_lines(items) for name, items in card.genre_beats.items()}
    if beats == card.genre_beats and all(update[key] == list(getattr(card, key)) for key in update):
        return card
    update["genre_beats"] = beats
    return card.model_copy(update=update)
