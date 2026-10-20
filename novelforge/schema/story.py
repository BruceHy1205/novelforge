"""Public story layer: the hook, the people, and what the reader is waiting for.

Everything here is writer-visible. It must never hold a secret's text. A
suspect's `public_face` is what the town sees, not who they are.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

ExpectationKind = Literal["main", "side"]


class Character(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    name: str = ""
    # Free text: each genre names the roles it needs in `Genre.required_roles`.
    role: str = "other"
    public_face: str = ""
    want: str = ""
    stake: str = ""
    edge: str = ""
    surface_motive: str = ""
    surface_opportunity: str = ""


class Expectation(BaseModel):
    """Something specific the reader wants to see. Paid off in `payoff_scene_id`."""

    model_config = ConfigDict(extra="forbid")

    id: str
    kind: ExpectationKind = "main"
    promise: str = ""
    payoff_scene_id: str = ""


class Theme(BaseModel):
    """A question the book keeps asking through choices, not a moral it states.

    `tension` holds two answers that both have a case. `arc` is how the
    protagonist's answer moves across the book; later chapters may bend it.
    """

    model_config = ConfigDict(extra="forbid")

    id: str
    question: str = ""
    tension: str = ""
    arc: list[str] = Field(default_factory=list)


class Approach(BaseModel):
    """写作思路. `engine` is the reading drive every chapter repeats and escalates."""

    model_config = ConfigDict(extra="forbid")

    engine: str = ""
    voice: str = ""
    motifs: list[str] = Field(default_factory=list)
    principles: list[str] = Field(default_factory=list)

    def texts(self) -> list[str]:
        return [self.engine, self.voice, *self.motifs, *self.principles]


class StoryBible(BaseModel):
    """`hook` is the one-line pitch. `edge` on the protagonist is the 金手指.

    `core` is the one feeling the reader comes back for (爽、揪心、被看见…);
    `themes` and `approach` say what the book is about and how it is told.
    """

    model_config = ConfigDict(extra="forbid")

    hook: str = ""
    selling_point: str = ""
    tone: str = ""
    # Public situation before chapter one: era, place, and what is already true.
    background: str = ""
    # The one public rule this book stands on. Not the feeling in `core`.
    concept: str = ""
    core: str = ""
    themes: list[Theme] = Field(default_factory=list)
    approach: Approach = Field(default_factory=Approach)
    protagonist_id: str = ""
    characters: list[Character] = Field(default_factory=list)
    expectations: list[Expectation] = Field(default_factory=list)

    def protagonist(self) -> Character | None:
        if self.protagonist_id:
            for person in self.characters:
                if person.id == self.protagonist_id:
                    return person
        return next((person for person in self.characters if person.role == "protagonist"), None)

    def texts(self) -> list[str]:
        values = [
            self.hook,
            self.selling_point,
            self.tone,
            self.background,
            self.concept,
            self.core,
        ]
        for theme in self.themes:
            values.extend([theme.question, theme.tension, *theme.arc])
        values.extend(self.approach.texts())
        for person in self.characters:
            values.extend(
                [
                    person.name,
                    person.public_face,
                    person.want,
                    person.stake,
                    person.edge,
                    person.surface_motive,
                    person.surface_opportunity,
                ]
            )
        values.extend(item.promise for item in self.expectations)
        return [value for value in values if value]


class Pitch(BaseModel):
    model_config = ConfigDict(extra="forbid")

    hook: str = ""
    selling_point: str = ""
    protagonist: str = ""
    opening_image: str = ""


class PitchDeck(BaseModel):
    model_config = ConfigDict(extra="forbid")

    pitches: list[Pitch] = Field(default_factory=list)


class PitchScore(BaseModel):
    """1–5. `would_open`: would this reader tap into chapter one."""

    model_config = ConfigDict(extra="forbid")

    score: int = Field(default=3, ge=1, le=5)
    would_open: bool = True
    reason: str = ""


class PlausibilityReport(BaseModel):
    model_config = ConfigDict(extra="forbid")

    plausible: bool = True
    fair_play: bool = True
    problems: list[str] = Field(default_factory=list)
