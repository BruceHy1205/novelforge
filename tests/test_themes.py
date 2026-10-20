"""Core feeling, themes, and writing approach: public, screened, and carried forward."""

from __future__ import annotations

from pathlib import Path

import pytest
from pydantic import BaseModel

from novelforge.llm.fake import FakeLLMClient
from novelforge.pipeline import run_plan, run_scene
from novelforge.roles.architect import sanitize_canon
from novelforge.roles.critic import CriticVerdict, render_brief
from novelforge.roles.guess_judge import KeywordJudge
from novelforge.roles.planner import SYSTEM_PROMPT as PLANNER_PROMPT
from novelforge.roles.prose import Prose, SceneDeck
from novelforge.roles.themes import StoryCore, draft_core, screen_core
from novelforge.roles.writer import SYSTEM_PROMPT as WRITER_PROMPT
from novelforge.schema.canon import Canon, Secret
from novelforge.schema.gate import GateResult
from novelforge.schema.memory import ThemeNote
from novelforge.schema.reader import Persona, ReaderGuess, ReaderReport
from novelforge.schema.scene import SceneCard
from novelforge.schema.state import BookState
from novelforge.schema.story import Approach, Character, StoryBible, Theme
from novelforge.store import load_canon, save_canon
from novelforge.view.filter import SecretLeakError, build_writer_view

SECRET = "凶手用铁丝把钥匙推回屋里"

STORY = StoryBible(
    hook="聋孩子是唯一的目击者",
    core="被所有人当成没用的人，却用只有他能做到的方式扳回一城",
    themes=[
        Theme(
            id="T-1",
            question="没人肯听的证词还算不算证词？",
            tension="说出来会被当成疯子；不说，真相就跟着死者一起沉下去",
            arc=["他以为没人会信", "他开始自己找证据", "他选择当众开口"],
        )
    ],
    approach=Approach(
        engine="每章他看见一件别人看不见的事，又因此付出更大的代价",
        voice="贴着主角感官的近距离第三人称",
        motifs=["速写本"],
        principles=["情绪落在动作上"],
    ),
    protagonist_id="char-1",
    characters=[Character(id="char-1", name="闻笛", role="protagonist", edge="读唇")],
)


def _canon(story: StoryBible = STORY) -> Canon:
    secret = Secret(id="S-1", title="钥匙", text=SECRET, probe_question="门是怎么锁上的？")
    return Canon(title="雨棚", story=story, secrets=[secret])


def test_core_and_themes_reach_the_writer_with_the_chapter_beat() -> None:
    card = SceneCard(scene_id="sc-02", theme_beat="他把速写本推过去", reader_feeling="憋屈")
    book = BookState(canon=_canon(), theme_notes=[ThemeNote(scene_id="sc-01", text="他没开口")])
    view = build_writer_view(book, card)
    assert view.story.core == STORY.core
    assert view.story.themes[0].question == STORY.themes[0].question
    assert view.story.approach.engine == STORY.approach.engine
    assert view.scene.theme_beat == "他把速写本推过去"
    assert view.scene.reader_feeling == "憋屈"
    assert view.theme_notes == ["他没开口"]


def test_a_theme_cannot_carry_a_secret() -> None:
    leaky = STORY.model_copy(update={"themes": [Theme(id="T-1", question=SECRET)]})
    with pytest.raises(SecretLeakError):
        build_writer_view(BookState(canon=_canon(leaky)), SceneCard(scene_id="sc-01"))
    with pytest.raises(SecretLeakError):
        build_writer_view(BookState(canon=_canon()), SceneCard(scene_id="sc-01", theme_beat=SECRET))
    note = ThemeNote(scene_id="sc-01", text=SECRET)
    with pytest.raises(SecretLeakError):
        build_writer_view(
            BookState(canon=_canon(), theme_notes=[note]), SceneCard(scene_id="sc-01")
        )


def test_sanitize_scrubs_themes_and_approach() -> None:
    dirty = STORY.model_copy(
        update={
            "core": f"爽：{SECRET}",
            "themes": [Theme(id="", question="谁信他？", arc=[SECRET, "开口"])],
            "approach": Approach(engine=f"其实{SECRET}", motifs=[SECRET, "速写本"]),
        }
    )
    clean = sanitize_canon(_canon(dirty), 4).story
    assert SECRET not in clean.model_dump_json()
    assert clean.themes[0].id == "T-1"
    assert clean.themes[0].arc == ["开口"]
    assert clean.approach.motifs == ["速写本"]


def test_a_canon_without_themes_gets_them_drafted_and_scrubbed() -> None:
    bare = _canon(StoryBible(hook="雨夜"))
    drafted = StoryCore(
        core="扳回一城",
        themes=[Theme(id="T-1", question="谁信他？", arc=[SECRET, "开口"])],
    )
    client = FakeLLMClient(canned={StoryCore: drafted})
    canon = draft_core(bare, client, scenes=4)
    assert canon.story.core == "扳回一城"
    assert canon.story.themes[0].arc == ["开口"]
    assert canon.story.hook == "雨夜"
    assert client.calls[0]["role"] == "architect"


def test_a_theme_a_blind_reader_can_solve_from_is_dropped() -> None:
    giveaway = Theme(id="T-2", question="一根铁丝能不能锁住一扇门？")

    def respond(messages: list[dict[str, str]], model: type[BaseModel]) -> BaseModel | None:
        if model is ReaderReport:
            text = messages[-1]["content"]
            guess = "有人用铁丝推钥匙" if "铁丝" in text else "不知道"
            confidence = "certain" if "铁丝" in text else "none"
            return ReaderReport(
                persona_id="p",
                guesses=[ReaderGuess(probe_id="S-1", guess=guess, confidence=confidence)],
            )
        return None

    canon = _canon(STORY.model_copy(update={"themes": [*STORY.themes, giveaway]}))
    screened = screen_core(
        canon, [Persona(id="p")], FakeLLMClient(responder=respond), KeywordJudge({"S-1": ["铁丝"]})
    )
    assert [theme.id for theme in screened.story.themes] == ["T-1"]
    assert screened.story.core == STORY.core


def test_plan_adds_themes_to_a_kept_canon(tmp_path: Path) -> None:
    def respond(_messages: list[dict[str, str]], model: type[BaseModel]) -> BaseModel | None:
        if model is StoryCore:
            return StoryCore(core="扳回一城", themes=[Theme(id="T-1", question="谁信他？")])
        if model is SceneDeck:
            return SceneDeck(scenes=[SceneCard(scene_id="x", theme_beat="他开口")])
        return None

    directory = tmp_path / "projects" / "demo"
    directory.mkdir(parents=True)
    save_canon(directory, _canon(StoryBible(hook="雨夜")))
    client = FakeLLMClient(responder=respond)
    run_plan(
        "demo",
        "雨",
        client,
        KeywordJudge({}),
        root=tmp_path,
        scenes=1,
        personas=[],
        keep_canon=True,
    )
    assert load_canon(directory).story.core == "扳回一城"


def test_critic_reads_the_brief_and_its_theme_note_is_kept() -> None:
    def respond(messages: list[dict[str, str]], model: type[BaseModel]) -> BaseModel | None:
        if model is Prose:
            return Prose(text="他把本子推过去。")
        if model is CriticVerdict:
            return CriticVerdict(choice=0, theme_note=f"他第一次开口；{SECRET}")
        if model is ReaderReport:
            return ReaderReport(persona_id="p", tension="high")
        return None

    client = FakeLLMClient(responder=respond)
    card = SceneCard(scene_id="sc-01", length=6, tension_target=0.3, theme_beat="他把本子推过去")
    result = run_scene(
        BookState(canon=_canon()),
        card,
        ["sc-01"],
        client,
        KeywordJudge({"S-1": [SECRET]}),
        [Persona(id="p")],
    )
    assert result["status"] == "locked"
    brief = next(call for call in client.calls if call["role"] == "critic")["messages"][-1]
    assert STORY.core in brief["content"] and "他把本子推过去" in brief["content"]
    notes = result["book"].theme_notes
    assert [note.scene_id for note in notes] == ["sc-01"]
    assert SECRET not in notes[0].text and "他第一次开口" in notes[0].text


def test_a_missed_theme_asks_for_one_advisory_rewrite() -> None:
    def respond(_messages: list[dict[str, str]], model: type[BaseModel]) -> BaseModel | None:
        if model is Prose:
            return Prose(text="他把本子推过去。")
        if model is CriticVerdict:
            return CriticVerdict(choice=0, theme_hit=False, notes=["选择没写出来"])
        if model is ReaderReport:
            return ReaderReport(persona_id="p", tension="high")
        return None

    client = FakeLLMClient(responder=respond)
    result = run_scene(
        BookState(canon=_canon()),
        SceneCard(scene_id="sc-01", length=6, tension_target=0.3),
        ["sc-01"],
        client,
        KeywordJudge({}),
        [Persona(id="p")],
    )
    assert result["status"] == "locked"
    roles = [call["role"] for call in client.calls]
    assert roles.count("reviser") == 1
    revise = next(call for call in client.calls if call["role"] == "reviser")
    assert "选择没写出来" in revise["messages"][-1]["content"]
    assert result["book"].gate_stats["theme"].failures == 1


def test_brief_uses_public_fields_only() -> None:
    view = build_writer_view(
        BookState(canon=_canon()), SceneCard(scene_id="sc-01", reader_feeling="憋屈")
    )
    brief = render_brief(view.story, view.scene)
    assert "核心体验" in brief and "叙事引擎" in brief and "本章读者感受：憋屈" in brief
    assert "本章主题落点" not in brief
    assert SECRET not in brief


def test_prompts_carry_the_theme_layer() -> None:
    assert "theme_beat" in PLANNER_PROMPT and "story.core" in PLANNER_PROMPT
    assert "theme_beat" in WRITER_PROMPT and "theme_notes" in WRITER_PROMPT
    assert "不让人物讲道理" in WRITER_PROMPT
    assert GateResult(gate_id="theme", passed=False).advisory().blocking is False
