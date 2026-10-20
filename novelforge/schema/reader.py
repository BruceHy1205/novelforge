"""Reader simulation state and reports.

Confidence is a coarse bin (`none|hint|suspect|certain`). A 0–1 float is
accepted only through `eval.metrics.bin_confidence`; treating a model-emitted
float as a calibrated probability is a fake-precision risk.

The simulator never sees Canon. It answers public `ReaderProbe` questions
("who is the killer?") with free-text guesses; a separate canon-side judge
maps guesses onto secret IDs to update `ReaderState.secret_confidence`.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

ConfidenceBin = Literal["none", "hint", "suspect", "certain"]
Confidence = ConfidenceBin | float
TensionBin = Literal["flat", "low", "medium", "high"]

CONFIDENCE_ORDER: tuple[ConfidenceBin, ...] = ("none", "hint", "suspect", "certain")


class Persona(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    name: str = ""
    traits: list[str] = Field(default_factory=list)
    reading_style: str = ""


ReaderPersona = Persona


class ReaderProbe(BaseModel):
    """A public question asked of the simulated reader. Must not contain the answer."""

    model_config = ConfigDict(extra="forbid")

    probe_id: str
    question: str


class ReaderGuess(BaseModel):
    model_config = ConfigDict(extra="forbid")

    probe_id: str
    guess: str = ""
    confidence: ConfidenceBin = "none"


class SkipSpan(BaseModel):
    """Paragraphs (0-based, inclusive) in a scene the reader wanted to skip.

    Paragraphs, not character offsets: neither models nor human readers can
    point at character positions reliably.
    """

    model_config = ConfigDict(extra="forbid")

    scene_id: str
    paragraph_start: int = Field(ge=0)
    paragraph_end: int = Field(ge=0)
    reason: str = ""

    def paragraphs(self) -> set[int]:
        low, high = sorted((self.paragraph_start, self.paragraph_end))
        return set(range(low, high + 1))


class ReaderReport(BaseModel):
    """Outcome of `simulate_reader(manuscript, persona, probes)`. Uncalibrated in P0."""

    model_config = ConfigDict(extra="forbid")

    persona_id: str
    last_scene_id: str | None = None
    guesses: list[ReaderGuess] = Field(default_factory=list)
    wants_to_know: list[str] = Field(default_factory=list)
    skip_spans: list[SkipSpan] = Field(default_factory=list)
    tension: TensionBin | None = None
    would_continue: bool = True
    continue_reason: str = ""
    craving: str = ""
    boring_paragraph: int | None = Field(default=None, ge=0)
    notes: str = ""


class ReaderState(BaseModel):
    """Canon-side ledger per persona. Never handed to the writer as-is."""

    model_config = ConfigDict(extra="forbid")

    persona_id: str
    last_scene_id: str | None = None
    secret_confidence: dict[str, ConfidenceBin] = Field(default_factory=dict)
    open_questions: list[str] = Field(default_factory=list)
    remembered_clue_ids: list[str] = Field(default_factory=list)


class PublicReaderState(BaseModel):
    """Writer-visible reader state: what the audience is wondering, no secret IDs."""

    model_config = ConfigDict(extra="forbid")

    last_scene_id: str | None = None
    open_questions: list[str] = Field(default_factory=list)


class POVState(BaseModel):
    """Canon-side viewpoint ledger. Secret IDs here never reach the writer."""

    model_config = ConfigDict(extra="forbid")

    character_id: str
    name: str = ""
    location: str = ""
    emotional_state: str = ""
    goal: str = ""
    known_secret_ids: list[str] = Field(default_factory=list)
    blocked_secret_ids: list[str] = Field(default_factory=list)


class PublicPOVState(BaseModel):
    model_config = ConfigDict(extra="forbid")

    character_id: str = ""
    location: str = ""
    emotional_state: str = ""
    goal: str = ""
