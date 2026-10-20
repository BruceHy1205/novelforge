"""Whitelist constructor for WriterView. Hidden secrets must not cross this line."""

from __future__ import annotations

import re

from novelforge.roles.memory import earlier_lines
from novelforge.schema.canon import hidden_secret_ids, iter_secret_texts
from novelforge.schema.reader import PublicPOVState, PublicReaderState
from novelforge.schema.scene import (
    BEAT_FIELDS,
    CRAFT_FIELDS,
    PublicSceneCard,
    SceneCard,
    WriterView,
)
from novelforge.schema.state import BookState

PREV_TAIL_CHARS = 600
THEME_NOTES = 3


class SecretLeakError(ValueError):
    """Raised when hidden secret text or a hidden secret ID would enter WriterView."""


def build_writer_view(
    state: BookState,
    card: SceneCard,
    *,
    prev_tail_chars: int = PREV_TAIL_CHARS,
) -> WriterView:
    """Project BookState + SceneCard onto the writer whitelist.

    Each field is copied explicitly. A secret is "hidden" unless it is already
    revealed in `state.revealed_secret_ids` or listed in `card.must_reveal`;
    hidden secret texts and IDs may not appear anywhere in the view.
    Author-written fields that contain hidden text raise `SecretLeakError`;
    simulator-derived reader questions that happen to contain it are dropped.
    """

    secret_ids = {secret.id for secret in state.canon.secrets}
    revealed = set(state.revealed_secret_ids) | (set(card.must_reveal) & secret_ids)
    secret_texts = [text for _, text in iter_secret_texts(state.canon, revealed)]
    hidden_ids = hidden_secret_ids(state.canon, revealed)

    def check(where: str, *values: str) -> None:
        for value in values:
            if _contains_any(value, secret_texts):
                raise SecretLeakError(f"hidden secret text in {where}")

    check("scene.title", card.title)
    check("scene.beat_purpose", card.beat_purpose)
    check("scene.setting", card.setting)
    check("scene.ending_hook", card.ending_hook)
    check("scene.answers_hook", card.answers_hook)
    check("scene.beat", *(str(getattr(card, name)) for name in BEAT_FIELDS))
    check("scene.craft", *(line for name in CRAFT_FIELDS for line in getattr(card, name)))
    check("scene.genre_beats", *(line for lines in card.genre_beats.values() for line in lines))
    check("ledger", *state.ledger_have, *state.ledger_spent)
    check("story", *state.canon.story.texts())
    check("directives", *card.directives)
    check("style_samples", *state.style_samples)
    check("banned_patterns", *state.banned_patterns)
    earlier = earlier_lines(state.locked_scenes, state.summaries)
    check("summaries", *(summary.text for summary in state.summaries))
    check("earlier_summaries", *earlier)
    theme_notes = [note.text for note in state.theme_notes[-THEME_NOTES:] if note.text]
    check("theme_notes", *theme_notes)

    pov = state.pov_states.get(card.pov_character_id)
    public_pov = PublicPOVState(character_id=card.pov_character_id)
    if pov is not None:
        check("pov_state", pov.location, pov.emotional_state, pov.goal)
        public_pov = PublicPOVState(
            character_id=pov.character_id,
            location=pov.location,
            emotional_state=pov.emotional_state,
            goal=pov.goal,
        )

    prev_tail = ""
    if state.locked_scenes and prev_tail_chars > 0:
        prev_tail = state.locked_scenes[-1].text[-prev_tail_chars:]
        check("prev_tail", prev_tail)

    view = WriterView(
        scene=PublicSceneCard(
            scene_id=card.scene_id,
            title=card.title,
            beat_purpose=card.beat_purpose,
            pace=card.pace,
            length=card.length,
            tension_target=card.tension_target,
            pov_character_id=card.pov_character_id,
            setting=card.setting,
            ending_hook=card.ending_hook,
            answers_hook=card.answers_hook,
            reader_want=card.reader_want,
            obstacle=card.obstacle,
            payoff=card.payoff,
            state_change=card.state_change,
            theme_beat=card.theme_beat,
            reader_feeling=card.reader_feeling,
            opening_task=card.opening_task,
            beats=list(card.beats),
            plants=list(card.plants),
            misdirection=list(card.misdirection),
            genre_beats={name: list(lines) for name, lines in card.genre_beats.items()},
        ),
        story=state.canon.story.model_copy(deep=True),
        reader_state=_public_reader_state(state, secret_texts),
        pov_state=public_pov,
        directives=list(card.directives),
        prev_tail=prev_tail,
        style_samples=list(state.style_samples),
        banned_patterns=list(state.banned_patterns),
        earlier_summaries=earlier,
        theme_notes=theme_notes,
        ledger_have=list(state.ledger_have),
        ledger_spent=list(state.ledger_spent),
    )
    _assert_view_is_clean(view, secret_texts, hidden_ids)
    return view


def _public_reader_state(state: BookState, secret_texts: list[str]) -> PublicReaderState:
    questions: list[str] = []
    last_scene_id: str | None = None
    for reader in state.reader_states.values():
        last_scene_id = reader.last_scene_id or last_scene_id
        for question in reader.open_questions:
            if question in questions or _contains_any(question, secret_texts):
                continue
            questions.append(question)
    return PublicReaderState(last_scene_id=last_scene_id, open_questions=questions)


def _contains_any(value: str, needles: list[str]) -> bool:
    return any(needle and needle in value for needle in needles)


def _assert_view_is_clean(
    view: WriterView,
    secret_texts: list[str],
    hidden_ids: list[str],
) -> None:
    blob = view.model_dump_json()
    if _contains_any(blob, secret_texts):
        raise SecretLeakError("hidden secret text present in WriterView JSON")
    for secret_id in hidden_ids:
        if re.search(rf"(?<![\w-]){re.escape(secret_id)}(?![\w-])", blob):
            raise SecretLeakError(f"hidden secret id {secret_id} present in WriterView JSON")
