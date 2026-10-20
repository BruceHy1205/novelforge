"""Plan-time checks a genre can turn on. Mystery leaves them off.

The edge audit and the card audit ask the gate model. Continuity is code:
a later scene must pick up the previous hook, and a genre's beat fields
must actually be filled. A failed audit is handed back for one redraft.
If it still fails, `PlanRejected` is raised and the caller must not save.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from novelforge.genres.base import Genre
from novelforge.schema.scene import SceneCard


class PlanRejected(RuntimeError):
    """A genre audit still failed after the one allowed redraft.

    The caller must not save what this pass produced. A failed canon audit
    leaves `canon.yaml` unwritten; a failed card audit leaves the scene files
    unwritten.
    """


class AuditReport(BaseModel):
    model_config = ConfigDict(extra="forbid")

    problems: list[str] = Field(default_factory=list)


def continuity_problems(cards: list[SceneCard], genre: Genre) -> list[str]:
    """Hooks have to hand off, and the genre's own beats have to be present."""

    problems: list[str] = []
    last = len(cards) - 1
    for index, card in enumerate(cards):
        if index < last and not card.ending_hook.strip():
            problems.append(f"{card.scene_id} 没有结尾钩子，下一场没法接")
        if index and not card.answers_hook.strip():
            problems.append(f"{card.scene_id} 没有接上一场结尾的那件事")
        missing = [name for name in genre.beat_fields if not card.genre_beats.get(name)]
        if missing:
            problems.append(f"{card.scene_id} 缺专属节拍 {'、'.join(missing)}")
    return problems


def review_text(prompt: str, client: Any, **fields: str) -> list[str]:
    report = client.complete(
        messages=[{"role": "user", "content": prompt.format(**fields)}],
        response_model=AuditReport,
        role="gate",
    )
    return [item for item in report.problems if item.strip()]
