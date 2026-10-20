"""Structured prose returned by the writer, reviser, and baseline."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field

from novelforge.schema.scene import SceneCard


class Prose(BaseModel):
    model_config = ConfigDict(extra="forbid")

    text: str


class ParagraphFix(BaseModel):
    """One paragraph replacement. Other paragraphs stay as written."""

    model_config = ConfigDict(extra="forbid")

    index: int = Field(ge=0)
    text: str


class ParagraphFixes(BaseModel):
    model_config = ConfigDict(extra="forbid")

    fixes: list[ParagraphFix] = Field(default_factory=list)


class SceneDeck(BaseModel):
    model_config = ConfigDict(extra="forbid")

    scenes: list[SceneCard] = Field(default_factory=list)
