"""Clues planted in scenes. Author-only wording is not writer-visible."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict

ClueVisibility = Literal["public", "author_only"]
ClueStrength = Literal["trace", "notice", "pointer"]


class Clue(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    text: str
    secret_id: str | None = None
    visibility: ClueVisibility = "public"
    planted_in: str | None = None
    strength: ClueStrength = "trace"
