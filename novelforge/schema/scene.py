"""Scene cards, locked scenes, and the writer-visible projection."""

from __future__ import annotations

import hashlib
from datetime import UTC, datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from novelforge.schema.reader import PublicPOVState, PublicReaderState
from novelforge.schema.story import StoryBible

HintBudgetBin = Literal["none", "light", "moderate", "heavy"]
HintBudget = HintBudgetBin | float
PaceBin = Literal["slack", "steady", "tight", "sprint"]
Pace = PaceBin | str
OpeningTask = Literal["", "入局", "加压", "承诺"]

# Writer-visible craft fields on a card. Expectation → obstacle → payoff is the
# 期待 / 压抑 / 释放 beat; `state_change` is what the payoff leaves different.
# `theme_beat` is the choice or cost through which this chapter touches a
# theme; `reader_feeling` is what the reader should feel when it ends.
BEAT_FIELDS: tuple[str, ...] = (
    "reader_want",
    "obstacle",
    "payoff",
    "state_change",
    "theme_beat",
    "reader_feeling",
    "opening_task",
)

# Writer-visible chapter craft. `beats` is the 起承转合 outline, `plants` are
# details a reader should be able to find again after the reveal, and
# `misdirection` points somewhere wrong. All three are visible text only and
# pass the same leak checks as directives.
CRAFT_FIELDS: tuple[str, ...] = ("beats", "plants", "misdirection")
# `genre_beats` holds the genre's own visible beat lists (keys from
# `Genre.beat_fields`), under the same leak checks as the craft fields. Left
# out of dumps when empty so genres without beat fields keep their old prompts.


class SceneCard(BaseModel):
    """Full planner/gate card. `must_reveal` / `must_withhold` hold opaque IDs."""

    model_config = ConfigDict(extra="forbid")

    scene_id: str
    title: str = ""
    beat_purpose: str = ""
    must_reveal: list[str] = Field(default_factory=list)
    must_withhold: list[str] = Field(default_factory=list)
    hint_budget: HintBudget = "light"
    pace: Pace = "steady"
    length: int = 2000
    tension_target: float = Field(default=0.5, ge=0.0, le=1.0)
    directives: list[str] = Field(default_factory=list)
    pov_character_id: str = ""
    setting: str = ""
    ending_hook: str = ""
    answers_hook: str = ""
    reader_want: str = ""
    obstacle: str = ""
    payoff: str = ""
    state_change: str = ""
    theme_beat: str = ""
    reader_feeling: str = ""
    opening_task: OpeningTask = ""
    beats: list[str] = Field(default_factory=list)
    plants: list[str] = Field(default_factory=list)
    misdirection: list[str] = Field(default_factory=list)
    genre_beats: dict[str, list[str]] = Field(default_factory=dict, exclude_if=lambda v: not v)


class PublicSceneCard(BaseModel):
    """Writer-visible slice of a scene card.

    Excludes `must_reveal`, `must_withhold`, and `hint_budget`: the writer must
    not learn that something is being hidden or how hard to hint at it.
    """

    model_config = ConfigDict(extra="forbid")

    scene_id: str
    title: str = ""
    beat_purpose: str = ""
    pace: Pace = "steady"
    length: int = 2000
    tension_target: float = Field(default=0.5, ge=0.0, le=1.0)
    pov_character_id: str = ""
    setting: str = ""
    ending_hook: str = ""
    answers_hook: str = ""
    reader_want: str = ""
    obstacle: str = ""
    payoff: str = ""
    state_change: str = ""
    theme_beat: str = ""
    reader_feeling: str = ""
    opening_task: OpeningTask = ""
    beats: list[str] = Field(default_factory=list)
    plants: list[str] = Field(default_factory=list)
    misdirection: list[str] = Field(default_factory=list)
    genre_beats: dict[str, list[str]] = Field(default_factory=dict, exclude_if=lambda v: not v)


class LockedScene(BaseModel):
    """Accepted manuscript text. The only manuscript form the reader sim reads."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    scene_id: str
    text: str
    locked_at: datetime
    sha256: str

    @classmethod
    def lock(cls, scene_id: str, text: str) -> LockedScene:
        return cls(
            scene_id=scene_id,
            text=text,
            locked_at=datetime.now(UTC),
            sha256=hashlib.sha256(text.encode("utf-8")).hexdigest(),
        )


class WriterView(BaseModel):
    """Whitelist projection. Extra fields are forbidden by constitution."""

    model_config = ConfigDict(extra="forbid")

    scene: PublicSceneCard
    story: StoryBible = Field(default_factory=StoryBible)
    reader_state: PublicReaderState = Field(default_factory=PublicReaderState)
    pov_state: PublicPOVState = Field(default_factory=PublicPOVState)
    directives: list[str] = Field(default_factory=list)
    prev_tail: str = ""
    style_samples: list[str] = Field(default_factory=list)
    banned_patterns: list[str] = Field(default_factory=list)
    earlier_summaries: list[str] = Field(default_factory=list)
    theme_notes: list[str] = Field(default_factory=list)
    ledger_have: list[str] = Field(default_factory=list, exclude_if=lambda value: not value)
    ledger_spent: list[str] = Field(default_factory=list, exclude_if=lambda value: not value)
