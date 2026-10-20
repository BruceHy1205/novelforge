"""Constitutional signature contracts for the reader simulator."""

from __future__ import annotations

import inspect
import typing

from novelforge.roles import critic, reader_sim
from novelforge.roles.critic import choose_draft
from novelforge.roles.reader_sim import simulate_reader

FORBIDDEN_TYPES = {"Canon", "SceneCard", "BookState", "Secret", "RevealPlanItem", "WriterView"}
FORBIDDEN_NAMES = {"canon", "scene", "scene_card", "card", "book", "state", "secrets"}


def _type_names(annotation: object) -> set[str]:
    names = {getattr(annotation, "__name__", "")}
    for arg in typing.get_args(annotation):
        names |= _type_names(arg)
    return names


def test_simulate_reader_parameters() -> None:
    names = list(inspect.signature(simulate_reader).parameters)
    assert names == ["manuscript", "persona", "probes", "client"]
    assert not FORBIDDEN_NAMES & set(names)


def test_simulate_reader_annotations_exclude_canon_types() -> None:
    hints = typing.get_type_hints(simulate_reader, vars(reader_sim))
    hints.pop("return", None)
    for name, annotation in hints.items():
        leaked = _type_names(annotation) & FORBIDDEN_TYPES
        assert not leaked, f"parameter {name} accepts {leaked}"
    assert "LockedScene" in _type_names(hints["manuscript"])


def test_critic_sees_only_manuscript_and_drafts() -> None:
    names = list(inspect.signature(choose_draft).parameters)
    assert names == ["manuscript", "drafts", "client", "brief", "genre"]
    hints = typing.get_type_hints(choose_draft, vars(critic))
    hints.pop("return", None)
    assert hints["brief"] is str
    assert _type_names(hints["genre"]) - {""} <= {"Genre", "NoneType", "Optional", "Union"}
    for name, annotation in hints.items():
        leaked = _type_names(annotation) & FORBIDDEN_TYPES
        assert not leaked, f"parameter {name} accepts {leaked}"
