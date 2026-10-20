"""Book-level state: the full author-side ledger the pipeline carries."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field

from novelforge.schema.canon import Canon
from novelforge.schema.clues import Clue
from novelforge.schema.memory import ChapterSummary, GateStat, ReviewMark, ThemeNote
from novelforge.schema.reader import POVState, ReaderState
from novelforge.schema.scene import LockedScene


def _default_banned() -> list[str]:
    from novelforge.gates.style import DEFAULT_BANNED

    return list(DEFAULT_BANNED)


class BookState(BaseModel):
    model_config = ConfigDict(extra="forbid")

    canon: Canon = Field(default_factory=Canon)
    locked_scenes: list[LockedScene] = Field(default_factory=list)
    revealed_secret_ids: list[str] = Field(default_factory=list)
    reader_states: dict[str, ReaderState] = Field(default_factory=dict)
    pov_states: dict[str, POVState] = Field(default_factory=dict)
    clues: list[Clue] = Field(default_factory=list)
    style_samples: list[str] = Field(default_factory=list)
    tension_trace: list[float] = Field(default_factory=list)
    banned_patterns: list[str] = Field(default_factory=_default_banned)
    gate_failures: dict[str, int] = Field(default_factory=dict)
    summaries: list[ChapterSummary] = Field(default_factory=list)
    archived_questions: list[str] = Field(default_factory=list)
    theme_notes: list[ThemeNote] = Field(default_factory=list)
    ledger_have: list[str] = Field(default_factory=list)
    ledger_spent: list[str] = Field(default_factory=list)
    review_marks: list[ReviewMark] = Field(default_factory=list)
    gate_stats: dict[str, GateStat] = Field(default_factory=dict)
    reader_sim_calls: int = 0
