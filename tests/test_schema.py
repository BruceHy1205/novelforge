from __future__ import annotations

import pytest
import yaml
from pydantic import ValidationError

from novelforge.project import EMPTY_CANON_YAML
from novelforge.schema.canon import Canon, Secret
from novelforge.schema.gate import GateResult
from novelforge.schema.reader import ReaderGuess, ReaderReport, ReaderState, SkipSpan
from novelforge.schema.scene import LockedScene, SceneCard, WriterView
from novelforge.schema.state import BookState


def test_empty_canon_yaml_validates() -> None:
    loaded = yaml.safe_load(EMPTY_CANON_YAML)
    canon = Canon.model_validate(loaded)
    assert canon.secrets == []
    assert canon.reveal_plan == []
    assert canon.title == ""


def test_scene_card_required_fields() -> None:
    card = SceneCard(
        scene_id="sc-01",
        beat_purpose="turn",
        must_reveal=["C-01"],
        must_withhold=["S-001"],
        hint_budget=0.2,
        pace="tight",
        length=1200,
        tension_target=0.7,
        directives=["end on a question"],
    )
    assert card.hint_budget == 0.2
    assert card.beat_purpose == "turn"


def test_writer_view_and_gate_result_roundtrip() -> None:
    from novelforge.schema.scene import PublicSceneCard

    view = WriterView(scene=PublicSceneCard(scene_id="sc-01"))
    GateResult(gate_id="literal", passed=True)
    ReaderState(persona_id="p1", secret_confidence={"S-1": "hint"})
    ReaderReport(
        persona_id="p1",
        guesses=[ReaderGuess(probe_id="S-1", guess="butler", confidence="suspect")],
        skip_spans=[SkipSpan(scene_id="sc-01", paragraph_start=2, paragraph_end=0)],
        tension="medium",
    )
    restored = WriterView.model_validate_json(view.model_dump_json())
    assert restored.scene.scene_id == "sc-01"


def test_confidence_rejects_floats_in_reports() -> None:
    with pytest.raises(ValidationError):
        ReaderGuess(probe_id="S-1", confidence=0.8)  # type: ignore[arg-type]


def test_locked_scene_is_frozen_and_hashed() -> None:
    import hashlib

    scene = LockedScene.lock("sc-01", "text")
    assert scene.sha256 == hashlib.sha256(b"text").hexdigest()
    with pytest.raises(ValidationError):
        scene.text = "edited"  # type: ignore[misc]


def test_book_state_roundtrips_through_json() -> None:
    book = BookState(
        canon=Canon(secrets=[Secret(id="S-1", title="t", text="x")]),
        locked_scenes=[LockedScene.lock("sc-01", "text")],
    )
    assert BookState.model_validate_json(book.model_dump_json()) == book


def test_secret_rejects_unknown_fields() -> None:
    with pytest.raises(ValidationError):
        Secret.model_validate({"id": "S-1", "title": "t", "text": "x", "leak": "no"})
