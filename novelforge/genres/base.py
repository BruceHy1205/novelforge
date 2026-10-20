"""A genre is a rule set on top of one engine.

The engine (scene graph, WriterView whitelist, reader simulator, memory,
routing) never changes per genre. A genre supplies prompt slots, what a
Canon must contain, card beat fields, the gate list with tiers, pacing, and
reader personas.

Leak gates are part of the constitution, not of a genre: every genre must
list them as blocking. With no secrets they pass trivially.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal

Tier = Literal["blocking", "advisory"]

PACES: tuple[str, ...] = ("slack", "steady", "tight", "sprint")

LEAK_GATES: tuple[str, ...] = ("literal", "directive", "inference", "reveal")

# Every slot a role template asks for. A genre must fill all of them.
PROMPT_SLOTS: tuple[str, ...] = (
    "pitch.identity",
    "pitch.protagonist",
    "architect.identity",
    "architect.cast",
    "architect.why",
    "architect.secret_count",
    "architect.secrets",
    "plausibility",
    "themes.identity",
    "themes.core",
    "themes.guard",
    "planner.identity",
    "planner.mission",
    "planner.stakes",
    "planner.beats",
    "planner.craft",
    "planner.no_spoil",
    "planner.opening",
    "writer.identity",
    "writer.craft",
    "writer.opening",
    "critic.identity",
    "critic.craft",
    "critic.setup",
    "reviser.leak",
    "reviser.hint",
    "reviser.skim",
    "judge.identity",
    "judge.examples",
    "baseline.kind",
)


class GenreError(ValueError):
    """A genre definition breaks the engine contract."""


@dataclass(frozen=True)
class Genre:
    """`beat_fields` names extra writer-visible card lists (`SceneCard.genre_beats`).

    `required_roles` maps a character role to the label used when the
    architect leaves it out. `knots` is the tension curve as (position,
    tension) pairs.
    """

    id: str
    name: str
    prompts: dict[str, str]
    pre_gates: tuple[tuple[str, Tier], ...]
    main_gates: tuple[tuple[str, Tier], ...]
    knots: tuple[tuple[float, float], ...]
    length_budget: dict[str, int]
    pace_craft: dict[str, str]
    personas: Path
    requires_secrets: bool = True
    required_roles: dict[str, str] = field(default_factory=dict)
    beat_fields: dict[str, str] = field(default_factory=dict)
    inference_tolerance: int = 1
    # Empty means off, so a genre that does not set these keeps its old call list.
    audit_edge: str = ""
    audit_cards: str = ""
    require_story: bool = False
    # Beat-field names that accumulate into the writer-visible ledger. Empty means off.
    ledger_gain: str = ""
    ledger_spent: str = ""

    def __post_init__(self) -> None:
        missing = [slot for slot in PROMPT_SLOTS if slot not in self.prompts]
        if missing:
            raise GenreError(f"{self.id}: missing prompt slots {missing}")
        tiers = dict((*self.pre_gates, *self.main_gates))
        for gate_id in LEAK_GATES:
            if tiers.get(gate_id) != "blocking":
                raise GenreError(f"{self.id}: leak gate {gate_id} must be listed as blocking")
        for table in (self.length_budget, self.pace_craft):
            if set(table) != set(PACES):
                raise GenreError(f"{self.id}: length_budget and pace_craft need {PACES}")

    def prompt(self, slot: str) -> str:
        return self.prompts[slot]


def fill(template: str, genre: Genre, prefix: str) -> str:
    """Replace `<<name>>` with `genre.prompt(f"{prefix}.{name}")`."""

    out = template
    for slot in PROMPT_SLOTS:
        if slot.startswith(f"{prefix}."):
            out = out.replace(f"<<{slot.removeprefix(prefix + '.')}>>", genre.prompt(slot))
    if "<<" in out:
        raise GenreError(f"unfilled slot in {prefix} template")
    return out
