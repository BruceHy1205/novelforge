"""Story layer, three-beat cards, pitch choice, plausibility, and the retention gate."""

from __future__ import annotations

import pytest
from pydantic import BaseModel

from novelforge.gates.retention import check_retention, retention_notes
from novelforge.llm.fake import FakeLLMClient
from novelforge.pacing.curve import tension_curve
from novelforge.pacing.pace import apply_pacing
from novelforge.pipeline import cast_pov
from novelforge.roles.architect import (
    IncompleteCanonError,
    choose_pitch,
    draft_canon,
    sanitize_canon,
)
from novelforge.roles.planner import open_with_protagonist
from novelforge.roles.prose import Prose
from novelforge.roles.reader_sim import SYSTEM_PROMPT as READER_PROMPT
from novelforge.roles.writer import draft_scene
from novelforge.schema.canon import Canon, Secret
from novelforge.schema.reader import Persona, ReaderReport
from novelforge.schema.scene import SceneCard
from novelforge.schema.state import BookState
from novelforge.schema.story import (
    Character,
    Expectation,
    Pitch,
    PitchDeck,
    PitchScore,
    PlausibilityReport,
    StoryBible,
)
from novelforge.view.filter import SecretLeakError, build_writer_view

SECRET = "凶手是楼上的水电工"

STORY = StoryBible(
    hook="她死后第三天，还在给全班发作业提醒",
    selling_point="每章拆穿一个嫌疑人的谎",
    protagonist_id="char-1",
    characters=[
        Character(
            id="char-1",
            name="许棠",
            role="protagonist",
            want="在停职前找到真凶",
            stake="她是最后一个见过死者的人",
            edge="能听出录音里被剪过的地方",
        ),
        Character(id="char-2", name="沈默", role="suspect", public_face="老实的水电工"),
    ],
    expectations=[Expectation(id="E-1", promise="看许棠当众拆穿第一个谎")],
)


def _canon() -> Canon:
    return Canon(
        title="雨棚",
        story=STORY,
        secrets=[Secret(id="S-1", title="凶手", text=SECRET, known_by=["沈默"])],
    )


def test_story_and_beat_fields_reach_the_writer() -> None:
    card = SceneCard(
        scene_id="sc-01",
        reader_want="想看许棠证明自己没撒谎",
        obstacle="队长当众收了她的证件",
        payoff="她从录音里听出被剪掉的三秒",
        state_change="她从嫌疑人变成唯一的线索",
        opening_task="入局",
        pov_character_id="char-1",
    )
    view = build_writer_view(BookState(canon=_canon()), card)
    assert view.story.hook == STORY.hook
    assert view.story.protagonist().name == "许棠"
    assert view.scene.reader_want == card.reader_want
    assert view.scene.opening_task == "入局"
    assert SECRET not in view.model_dump_json()


@pytest.mark.parametrize("field", ["reader_want", "obstacle", "payoff", "state_change"])
def test_a_beat_field_cannot_carry_a_secret(field: str) -> None:
    card = SceneCard(scene_id="sc-01", **{field: SECRET})
    with pytest.raises(SecretLeakError):
        build_writer_view(BookState(canon=_canon()), card)


def test_a_story_field_cannot_carry_a_secret() -> None:
    canon = _canon()
    leaky = canon.model_copy(update={"story": STORY.model_copy(update={"hook": SECRET})})
    with pytest.raises(SecretLeakError):
        build_writer_view(BookState(canon=leaky), SceneCard(scene_id="sc-01"))


def test_sanitize_scrubs_the_story_layer_and_fills_ids() -> None:
    story = STORY.model_copy(
        update={
            "protagonist_id": "",
            "selling_point": f"其实{SECRET}",
            "background": f"背景里夹着{SECRET}",
            "concept": f"设定里夹着{SECRET}",
            "characters": [Character(id="", name="许棠", role="protagonist")],
        }
    )
    clean = sanitize_canon(_canon().model_copy(update={"story": story}), 6).story
    assert SECRET not in clean.selling_point
    assert SECRET not in clean.background
    assert "背景里夹着" in clean.background
    assert SECRET not in clean.concept
    assert "设定里夹着" in clean.concept
    assert clean.characters[0].id == "char-1"
    assert clean.protagonist_id == "char-1"
    assert clean.expectations[0].payoff_scene_id == "sc-06"


def test_readers_pick_the_pitch_they_would_open() -> None:
    dull = Pitch(hook="警察查案")
    sharp = Pitch(hook="死者还在发消息")

    def respond(messages: list[dict[str, str]], model: type[BaseModel]) -> BaseModel | None:
        if model is PitchDeck:
            return PitchDeck(pitches=[dull, sharp])
        if model is PitchScore:
            text = messages[-1]["content"]
            if "死者还在发消息" in text:
                return PitchScore(score=5, would_open=True)
            return PitchScore(score=2, would_open=False)
        return None

    client = FakeLLMClient(responder=respond)
    assert choose_pitch("暴雨夜", client, [Persona(id="a"), Persona(id="b")]) == sharp


def test_an_implausible_canon_is_redrafted_once_with_the_problems() -> None:
    def respond(messages: list[dict[str, str]], model: type[BaseModel]) -> BaseModel | None:
        if model is Canon:
            return _canon()
        if model is PlausibilityReport:
            return PlausibilityReport(plausible=False, problems=["遥控刀刃做不到"])
        return None

    client = FakeLLMClient(responder=respond)
    draft_canon("暴雨夜", client, scenes=4)
    drafts = [call for call in client.calls if call["response_model"] == "Canon"]
    assert len(drafts) == 2
    assert "遥控刀刃做不到" in drafts[1]["messages"][-1]["content"]


def test_a_canon_with_the_truth_only_in_the_premise_is_redrafted_then_rejected() -> None:
    hollow = Canon(title="无声证词", premise=f"其实{SECRET}", story=StoryBible(hook="暴雨夜"))
    client = FakeLLMClient(canned={Canon: hollow})
    with pytest.raises(IncompleteCanonError, match="secrets"):
        draft_canon("暴雨夜", client, scenes=4)
    drafts = [call for call in client.calls if call["response_model"] == "Canon"]
    assert len(drafts) == 2
    assert "secrets 为空" in drafts[1]["messages"][-1]["content"]
    assert not any(call["response_model"] == "PlausibilityReport" for call in client.calls)


def test_a_redraft_that_times_out_keeps_the_first_canon() -> None:
    drafts = iter([_canon()])

    def respond(_messages: list[dict[str, str]], model: type[BaseModel]) -> BaseModel | None:
        if model is Canon:
            try:
                return next(drafts)
            except StopIteration:
                raise TimeoutError from None
        if model is PlausibilityReport:
            return PlausibilityReport(plausible=False, problems=["时间线不严"])
        return None

    canon = draft_canon("暴雨夜", FakeLLMClient(responder=respond), scenes=4)
    assert canon.secrets[0].text == SECRET


def test_golden_three_tasks_and_protagonist_viewpoint() -> None:
    cards = [SceneCard(scene_id=f"sc-{index:02d}") for index in range(1, 5)]
    filled = open_with_protagonist(cards, _canon())
    assert [card.opening_task for card in filled] == ["入局", "加压", "承诺", ""]
    assert {card.pov_character_id for card in filled} == {"char-1"}


def test_cast_gives_names_and_blocks_what_a_person_does_not_know() -> None:
    states = cast_pov(_canon())
    assert states["char-1"].name == "许棠"
    assert states["char-1"].goal == "在停职前找到真凶"
    assert states["char-1"].blocked_secret_ids == ["S-1"]
    assert states["char-2"].blocked_secret_ids == []


def test_the_opening_is_hot_and_not_steady() -> None:
    curve = tension_curve(8)
    assert curve[0] >= 0.65
    first = apply_pacing([SceneCard(scene_id=f"sc-{index:02d}") for index in range(1, 9)])[0]
    assert first.pace in {"tight", "sprint"}


def test_one_reader_walking_away_fails_an_opening_scene() -> None:
    stays = ReaderReport(persona_id="a", would_continue=True)
    leaves = ReaderReport(persona_id="b", would_continue=False, boring_paragraph=2)
    opening = check_retention([stays, stays, leaves], opening=True)
    assert opening.passed is False
    assert "paragraph 2" in " ".join(opening.reasons)
    assert check_retention([stays, stays, leaves], opening=False).passed is True
    assert check_retention([stays, leaves, leaves], opening=False).passed is False


def test_retention_notes_drop_secret_text() -> None:
    reports = [
        ReaderReport(persona_id="a", would_continue=False, continue_reason="主角没出场"),
        ReaderReport(persona_id="b", would_continue=False, continue_reason=f"我猜{SECRET}"),
        ReaderReport(persona_id="c", craving="看她拆穿队长"),
    ]
    notes = retention_notes(reports, [SECRET])
    assert notes == ["读者不想追：主角没出场", "读者最想看到：看她拆穿队长"]


def test_prompts_ask_for_retention_and_the_three_beats() -> None:
    assert "would_continue" in READER_PROMPT
    client = FakeLLMClient(canned={Prose: Prose(text="雨")})
    draft_scene(build_writer_view(BookState(canon=_canon()), SceneCard(scene_id="sc-01")), client)
    system = client.calls[0]["messages"][0]["content"]
    assert "reader_want" in system and "obstacle" in system and "payoff" in system
