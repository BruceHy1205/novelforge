"""Long-form memory and gate tallies. These stay on the author side of the filter."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

ReviewKind = Literal["canon", "opening", "payoff", "replan"]


class ChapterSummary(BaseModel):
    """Public recap of one finished chapter. Secret text is scrubbed before saving."""

    model_config = ConfigDict(extra="forbid")

    chapter_id: str
    scene_ids: list[str] = Field(default_factory=list)
    text: str = ""


class ThemeNote(BaseModel):
    """Where a locked chapter actually left the themes. Scrubbed of secret text."""

    model_config = ConfigDict(extra="forbid")

    scene_id: str
    text: str = ""


class ReviewMark(BaseModel):
    """A point a person could have read. The pipeline records it and does not wait."""

    model_config = ConfigDict(extra="forbid")

    kind: ReviewKind
    scene_id: str = ""


class GateStat(BaseModel):
    model_config = ConfigDict(extra="forbid")

    checks: int = 0
    failures: int = 0
