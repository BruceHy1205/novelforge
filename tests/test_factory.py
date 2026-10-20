"""The factory rejects a book it cannot stand behind, before any prose is written."""

from __future__ import annotations

from pathlib import Path

import pytest
from pydantic import BaseModel

from novelforge.genres import get_genre
from novelforge.llm.fake import FakeLLMClient
from novelforge.pipeline import run_plan
from novelforge.roles.architect import draft_canon
from novelforge.roles.audit import AuditReport, PlanRejected, continuity_problems
from novelforge.roles.guess_judge import KeywordJudge
from novelforge.roles.prose import SceneDeck
from novelforge.roles.themes import StoryGap
from novelforge.schema.canon import Canon
from novelforge.schema.reader import Persona
from novelforge.schema.scene import SceneCard
from novelforge.schema.story import Approach, Character, StoryBible, Theme
from novelforge.store import load_canon, load_cards

SHUANG = get_genre("shuangwen")


def _cast(edge: str) -> list[Character]:
    return [
        Character(id="c1", name="林昭", role="protagonist", edge=edge),
        Character(id="c2", name="赵衡", role="antagonist"),
    ]


def _story(edge: str = "吞废丹就变强") -> StoryBible:
    return StoryBible(
        hook="废灵根的杂役把旧丹吞了下去",
        themes=[Theme(id="T-1", question="借来的火算不算他自己的？")],
        protagonist_id="c1",
        characters=_cast(edge),
    )


def test_a_cheat_without_a_source_is_sent_back_once() -> None:
    drafted = iter(
        [
            Canon(title="吞丹", story=_story()),
            Canon(
                title="吞丹",
                story=_story("娘留下的旧丹里有半缕残识，只补他挑出的温丹，补完吐血"),
            ),
        ]
    )
    sent: list[str] = []

    def respond(messages: list[dict[str, str]], model: type[BaseModel]) -> BaseModel | None:
        if model is Canon:
            sent.append(messages[-1]["content"])
            return next(drafted)
        if model is AuditReport:
            if "吞废丹就变强" in messages[-1]["content"]:
                return AuditReport(problems=["金手指没有来历", "主角没有计谋"])
            return AuditReport()
        return None

    canon = draft_canon("废灵根", FakeLLMClient(responder=respond), scenes=4, genre=SHUANG)
    assert "残识" in canon.story.protagonist().edge
    assert len(sent) == 2
    assert "金手指没有来历" in sent[1]
    assert "主角没有计谋" in sent[1]


def test_broken_handoffs_and_missing_beats_are_named() -> None:
    cards = [
        SceneCard(scene_id="sc-01", ending_hook="", genre_beats={"face_slap": ["当众倒丹"]}),
        SceneCard(scene_id="sc-02", answers_hook="", genre_beats={}),
    ]
    problems = continuity_problems(cards, SHUANG)
    assert any("sc-01" in item and "结尾钩子" in item for item in problems)
    assert any("sc-02" in item and "没有接上" in item for item in problems)
    assert any("reaction" in item for item in problems)


def test_a_thin_story_keeps_its_themes_and_a_bad_deck_is_replanned_once(tmp_path: Path) -> None:
    story = _story("旧丹里的残识只补他挑出的温丹")
    loose = SceneCard(scene_id="sc-01", title="倒丹", genre_beats={"face_slap": ["倒了"]})
    linked = SceneCard(
        scene_id="sc-01",
        title="倒丹",
        ending_hook="调令拍在胸口",
        genre_beats={
            "face_slap": ["倒了"],
            "gain": ["一枚温丹"],
            "reaction": ["哄笑"],
            "spent": ["火晶用尽"],
        },
    )
    follow = linked.model_copy(update={"scene_id": "sc-02", "answers_hook": "他揣着调令到了矿口"})
    decks = iter([SceneDeck(scenes=[loose, loose]), SceneDeck(scenes=[linked, follow])])
    planner_notes: list[str] = []

    def respond(messages: list[dict[str, str]], model: type[BaseModel]) -> BaseModel | None:
        if model is Canon:
            return Canon(title="吞丹", story=story)
        if model is SceneDeck:
            planner_notes.append(messages[-1]["content"])
            return next(decks)
        if model is AuditReport:
            text = messages[-1]["content"]
            if "场景卡" in text and "调令拍在胸口" not in text:
                return AuditReport(problems=["sc-02 开头没有接调令"])
            return AuditReport()
        if model is StoryGap:
            return StoryGap(core="把倒掉的最后一步补完", engine="他先挑丹，残识只补这一步")
        return None

    client = FakeLLMClient(responder=respond)
    run_plan(
        "zhang",
        "废灵根",
        client,
        KeywordJudge({}),
        root=tmp_path,
        scenes=2,
        personas=[Persona(id="p")],
        genre="shuangwen",
    )
    saved = load_canon(tmp_path / "projects" / "zhang")
    assert saved.story.themes[0].id == "T-1"
    assert saved.story.core == "把倒掉的最后一步补完"
    assert "挑丹" in saved.story.approach.engine
    assert not any(call["response_model"] == "StoryCore" for call in client.calls)
    assert len(planner_notes) == 2
    assert "sc-02 开头没有接调令" in planner_notes[1]
    cards = load_cards(tmp_path / "projects" / "zhang")
    assert cards[1].answers_hook == "他揣着调令到了矿口"
    assert set(cards[0].genre_beats) == {"face_slap", "gain", "reaction", "spent"}


def test_a_second_failed_edge_audit_is_not_returned() -> None:
    drafts = 0

    def respond(messages: list[dict[str, str]], model: type[BaseModel]) -> BaseModel | None:
        nonlocal drafts
        if model is Canon:
            drafts += 1
            return Canon(title="吞丹", story=_story())
        if model is AuditReport:
            return AuditReport(problems=["金手指没有来历"])
        return None

    with pytest.raises(PlanRejected, match="金手指没有来历"):
        draft_canon("废灵根", FakeLLMClient(responder=respond), scenes=4, genre=SHUANG)
    assert drafts == 2


def test_a_rejected_canon_is_not_saved(tmp_path: Path) -> None:
    def respond(messages: list[dict[str, str]], model: type[BaseModel]) -> BaseModel | None:
        if model is Canon:
            return Canon(title="吞丹", story=_story())
        if model is AuditReport:
            return AuditReport(problems=["金手指没有来历"])
        return None

    with pytest.raises(PlanRejected, match="金手指没有来历"):
        run_plan(
            "zhang",
            "废灵根",
            FakeLLMClient(responder=respond),
            KeywordJudge({}),
            root=tmp_path,
            scenes=2,
            personas=[Persona(id="p")],
            genre="shuangwen",
        )
    directory = tmp_path / "projects" / "zhang"
    assert (directory / "idea.txt").is_file()
    assert not (directory / "canon.yaml").is_file()
    assert not list((directory / "scenes").glob("sc-*.yaml"))


def test_a_second_failed_deck_is_not_saved(tmp_path: Path) -> None:
    story = _story("旧丹里的残识只补他挑出的温丹").model_copy(
        update={"core": "当面扳回", "approach": Approach(engine="他先挑丹，残识只补这一步")}
    )
    thin = SceneCard(scene_id="sc-01", genre_beats={"face_slap": ["倒了"]})
    decks = 0

    def respond(messages: list[dict[str, str]], model: type[BaseModel]) -> BaseModel | None:
        nonlocal decks
        if model is Canon:
            return Canon(title="吞丹", story=story)
        if model is SceneDeck:
            decks += 1
            return SceneDeck(scenes=[thin, thin.model_copy(update={"scene_id": "sc-02"})])
        if model is AuditReport:
            text = messages[-1]["content"]
            if "场景卡" in text:
                return AuditReport(problems=["本事自己长出来"])
            return AuditReport()
        return None

    with pytest.raises(PlanRejected, match="本事自己长出来"):
        run_plan(
            "zhang",
            "废灵根",
            FakeLLMClient(responder=respond),
            KeywordJudge({}),
            root=tmp_path,
            scenes=2,
            personas=[Persona(id="p")],
            genre="shuangwen",
        )
    directory = tmp_path / "projects" / "zhang"
    assert decks == 2
    assert (directory / "canon.yaml").is_file()
    assert not (directory / "state.yaml").is_file()
    assert not list((directory / "scenes").glob("sc-*.yaml"))
