"""Constitutional isolation: hidden secrets stay out of WriterView."""

from __future__ import annotations

import json

import pytest
from pydantic import ValidationError

from novelforge.schema.canon import (
    PUBLIC_ID_FIELDS,
    SECRET_TEXT_FIELDS,
    Canon,
    RevealPlanItem,
    Secret,
)
from novelforge.schema.clues import Clue
from novelforge.schema.reader import POVState, ReaderState
from novelforge.schema.scene import LockedScene, PublicSceneCard, SceneCard, WriterView
from novelforge.schema.state import BookState
from novelforge.view.filter import SecretLeakError, build_writer_view

# One unique token per classified secret field. Adding a field to
# SECRET_TEXT_FIELDS without a token here fails the registry test.
FIELD_TOKENS: dict[str, str] = {
    "Secret.title": "SECRET_TOKEN_SECRET_TITLE_ZX9Q7W4",
    "Secret.text": "SECRET_TOKEN_SECRET_TEXT_PL4M2N8",
    "Secret.internal_notes": "SECRET_TOKEN_SECRET_NOTES_K7J3H1",
    "RevealPlanItem.author_rationale": "SECRET_TOKEN_REVEAL_RATIONALE_B6C2D0",
}
AUTHOR_ONLY_CLUE_TOKEN = "SECRET_TOKEN_AUTHOR_ONLY_CLUE_R5T8Y1"
HIDDEN_ID = "S-001"
REVEALED_ID = "S-002"
REVEALED_TEXT = "The lighthouse keeper is the narrator's father."


def _token(model: str, field: str) -> str:
    return FIELD_TOKENS[f"{model}.{field}"]


def _book() -> tuple[BookState, SceneCard]:
    canon = Canon(
        title="Fog Harbor",
        premise="A coastal town waits for a ship that never arrives.",
        secrets=[
            Secret(
                id=HIDDEN_ID,
                category="identity",
                title=_token("Secret", "title"),
                text=_token("Secret", "text"),
                internal_notes=_token("Secret", "internal_notes"),
                probe_question="谁是凶手？",
                known_by=["char-butler"],
            ),
            Secret(id=REVEALED_ID, title="Keeper", text=REVEALED_TEXT),
        ],
        reveal_plan=[
            RevealPlanItem(
                secret_id=HIDDEN_ID,
                earliest_scene_id="sc-09",
                method="withhold",
                author_rationale=_token("RevealPlanItem", "author_rationale"),
            )
        ],
    )
    book = BookState(
        canon=canon,
        locked_scenes=[LockedScene.lock("sc-01", "Rain hammered the pier all night.")],
        reader_states={
            "p-fan": ReaderState(
                persona_id="p-fan",
                last_scene_id="sc-01",
                secret_confidence={HIDDEN_ID: "hint"},
                open_questions=["Why did the ship turn back?"],
                remembered_clue_ids=["C-99"],
            )
        },
        pov_states={
            "char-guest": POVState(
                character_id="char-guest",
                location="harbor inn",
                emotional_state="uneasy",
                known_secret_ids=[HIDDEN_ID],
                blocked_secret_ids=[HIDDEN_ID],
            )
        },
        clues=[
            Clue(id="C-01", text="A torn ticket on the pier"),
            Clue(
                id="C-99",
                text=AUTHOR_ONLY_CLUE_TOKEN,
                secret_id=HIDDEN_ID,
                visibility="author_only",
            ),
        ],
        style_samples=["Short sentences. Weather as mood."],
    )
    card = SceneCard(
        scene_id="sc-02",
        title="The landing",
        beat_purpose="establish unease",
        must_reveal=["C-01"],
        must_withhold=[HIDDEN_ID],
        hint_budget="moderate",
        pace="steady",
        length=1800,
        tension_target=0.4,
        directives=["The butler polishes the same glass twice."],
        pov_character_id="char-guest",
        setting="harbor inn",
    )
    return book, card


def test_secret_field_registry_covers_all_string_fields() -> None:
    models = {"Secret": Secret, "RevealPlanItem": RevealPlanItem}
    for name, model in models.items():
        classified = set(SECRET_TEXT_FIELDS[name]) | set(PUBLIC_ID_FIELDS[name])
        for field_name, field in model.model_fields.items():
            if field_name == "known_by":
                continue
            if "str" in str(field.annotation) and field_name not in classified:
                pytest.fail(f"{name}.{field_name} is not classified as secret or public")
        for field_name in SECRET_TEXT_FIELDS[name]:
            assert f"{name}.{field_name}" in FIELD_TOKENS


def test_writer_view_excludes_every_hidden_secret_field() -> None:
    book, card = _book()
    blob = build_writer_view(book, card).model_dump_json()

    for field_path, token in FIELD_TOKENS.items():
        assert token not in blob, f"{field_path} leaked into WriterView"
    assert AUTHOR_ONLY_CLUE_TOKEN not in blob


def test_writer_view_excludes_hidden_secret_ids_and_meta() -> None:
    book, card = _book()
    dumped = json.loads(build_writer_view(book, card).model_dump_json())
    blob = json.dumps(dumped)

    assert HIDDEN_ID not in blob
    assert "C-99" not in blob
    for forbidden in ("must_withhold", "withhold_ids", "must_reveal", "hint_budget"):
        assert forbidden not in blob
    assert "known_secret_ids" not in blob
    assert "secret_confidence" not in blob


def test_writer_view_carries_public_context() -> None:
    book, card = _book()
    view = build_writer_view(book, card)

    assert view.scene.scene_id == "sc-02"
    assert view.reader_state.open_questions == ["Why did the ship turn back?"]
    assert view.pov_state.location == "harbor inn"
    assert view.directives == ["The butler polishes the same glass twice."]
    assert view.prev_tail.endswith("pier all night.")
    assert view.style_samples == ["Short sentences. Weather as mood."]


def test_revealed_secret_may_appear_in_directives() -> None:
    book, card = _book()
    book = book.model_copy(update={"revealed_secret_ids": [REVEALED_ID]})
    card = card.model_copy(update={"directives": [f"Reveal: {REVEALED_TEXT}"]})
    view = build_writer_view(book, card)
    assert REVEALED_TEXT in view.directives[0]


def test_must_reveal_unlocks_secret_for_this_scene() -> None:
    book, card = _book()
    card = card.model_copy(
        update={"must_reveal": [REVEALED_ID], "directives": [f"Reveal: {REVEALED_TEXT}"]}
    )
    assert REVEALED_TEXT in build_writer_view(book, card).directives[0]


@pytest.mark.parametrize(
    "mutate",
    [
        lambda b, c: (b, c.model_copy(update={"directives": [FIELD_TOKENS["Secret.text"]]})),
        lambda b, c: (b, c.model_copy(update={"beat_purpose": FIELD_TOKENS["Secret.title"]})),
        lambda b, c: (b, c.model_copy(update={"directives": [f"remember {HIDDEN_ID}"]})),
        lambda b, c: (
            b.model_copy(update={"style_samples": [FIELD_TOKENS["Secret.internal_notes"]]}),
            c,
        ),
        lambda b, c: (
            b.model_copy(
                update={
                    "pov_states": {
                        "char-guest": POVState(
                            character_id="char-guest",
                            goal=FIELD_TOKENS["RevealPlanItem.author_rationale"],
                        )
                    }
                }
            ),
            c,
        ),
        lambda b, c: (
            b.model_copy(
                update={
                    "locked_scenes": [
                        LockedScene.lock("sc-01", f"... {FIELD_TOKENS['Secret.text']}")
                    ]
                }
            ),
            c,
        ),
    ],
    ids=["directive", "beat_purpose", "hidden_id", "style_sample", "pov_goal", "prev_tail"],
)
def test_author_fields_with_hidden_secrets_are_rejected(mutate) -> None:
    book, card = mutate(*_book())
    with pytest.raises(SecretLeakError):
        build_writer_view(book, card)


def test_reader_questions_containing_secret_text_are_dropped() -> None:
    book, card = _book()
    reader = book.reader_states["p-fan"].model_copy(
        update={"open_questions": [f"Is it {FIELD_TOKENS['Secret.text']}?", "Who rang the bell?"]}
    )
    book = book.model_copy(update={"reader_states": {"p-fan": reader}})
    view = build_writer_view(book, card)
    assert view.reader_state.open_questions == ["Who rang the bell?"]


def test_writer_view_forbids_extra_fields() -> None:
    scene = PublicSceneCard(scene_id="sc-01")
    with pytest.raises(ValidationError):
        WriterView.model_validate(
            {"scene": scene.model_dump(), "secrets": [{"text": "should be rejected"}]}
        )
    with pytest.raises(ValidationError):
        PublicSceneCard.model_validate({"scene_id": "sc-01", "must_withhold": ["S-001"]})
