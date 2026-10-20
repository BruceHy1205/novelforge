from __future__ import annotations

from dataclasses import replace
from pathlib import Path

import pytest
from pydantic import BaseModel

from novelforge.gates.registry import GateContext, GateSpec, register_gate
from novelforge.genres import (
    DEFAULT_GENRE,
    GenreError,
    genre_ids,
    get_genre,
    register_genre,
)
from novelforge.genres.mystery import MYSTERY
from novelforge.llm.fake import FakeLLMClient
from novelforge.pipeline import project_genre, run_plan, run_scene
from novelforge.project import create_project
from novelforge.roles.architect import structural_problems
from novelforge.roles.guess_judge import KeywordJudge
from novelforge.roles.memory import prompt_for_gate
from novelforge.roles.planner import scrub_secret_text
from novelforge.roles.planner import system_prompt as planner_prompt
from novelforge.roles.prose import Prose, SceneDeck
from novelforge.roles.writer import system_prompt as writer_prompt
from novelforge.schema.canon import Canon, Secret
from novelforge.schema.gate import GateResult
from novelforge.schema.reader import Persona, ReaderReport
from novelforge.schema.scene import SceneCard
from novelforge.schema.state import BookState
from novelforge.schema.story import Character, StoryBible
from novelforge.store import load_cards, load_genre_id
from novelforge.view.filter import SecretLeakError, build_writer_view


def _rule_gate(context: GateContext) -> GateResult:
    passed = "规则" in context.draft
    return GateResult(gate_id="test-rule", passed=passed, reasons=[] if passed else ["没写规则"])


RULE_GATE = register_gate(GateSpec("test-rule", "main", _rule_gate, prompt="planner"))

GHOST = register_genre(
    replace(
        MYSTERY,
        id="test-ghost",
        name="测试怪谈",
        prompts={
            **MYSTERY.prompts,
            "architect.identity": "怪谈架构师",
            "writer.identity": "怪谈作者",
            "planner.identity": "怪谈总编剧",
        },
        pre_gates=(("literal", "blocking"), ("directive", "blocking")),
        main_gates=(("inference", "blocking"), ("reveal", "blocking"), ("test-rule", "advisory")),
        knots=((0.0, 0.9), (1.0, 0.9)),
        requires_secrets=False,
        required_roles={"protagonist": "主角"},
        beat_fields={"rules": "本章出现或被打破的规则"},
    )
)


def test_mystery_is_the_default(tmp_path: Path) -> None:
    assert get_genre() is get_genre(DEFAULT_GENRE) is MYSTERY
    assert "mystery" in genre_ids()
    assert load_genre_id(tmp_path) is None
    assert project_genre(tmp_path) is MYSTERY


def test_unknown_genre_is_refused() -> None:
    with pytest.raises(GenreError, match="unknown genre"):
        get_genre("nope")


def test_a_genre_must_fill_every_prompt_slot() -> None:
    prompts = dict(MYSTERY.prompts)
    del prompts["writer.craft"]
    with pytest.raises(GenreError, match="writer.craft"):
        replace(MYSTERY, id="broken", prompts=prompts)


def test_leak_gates_are_blocking_in_every_genre() -> None:
    with pytest.raises(GenreError, match="inference"):
        replace(MYSTERY, id="soft", main_gates=(("inference", "advisory"), ("reveal", "blocking")))
    with pytest.raises(GenreError, match="reveal"):
        replace(MYSTERY, id="open", main_gates=(("inference", "blocking"),))


def test_genre_slots_change_role_prompts() -> None:
    assert "怪谈作者" in writer_prompt(GHOST)
    assert "本章出现或被打破的规则" in writer_prompt(GHOST)
    assert "怪谈总编剧" in planner_prompt(GHOST)
    assert "genre_beats" not in writer_prompt(MYSTERY)


def test_required_roles_come_from_the_genre() -> None:
    canon = Canon(
        story=StoryBible(
            hook="第七条是空白的",
            protagonist_id="c1",
            characters=[Character(id="c1", name="林", role="protagonist")],
        )
    )
    assert structural_problems(canon, GHOST) == []
    problems = structural_problems(canon, MYSTERY)
    assert any("嫌疑人" in problem for problem in problems)
    assert any("secrets" in problem for problem in problems)
    assert Character(id="x", role="规则制定者").role == "规则制定者"


def test_init_saves_the_genre(tmp_path: Path) -> None:
    directory = create_project("ghost", root=tmp_path, genre="test-ghost")
    assert load_genre_id(directory) == "test-ghost"
    assert project_genre(directory) is GHOST


def test_plan_uses_and_saves_the_genre(tmp_path: Path) -> None:
    story = StoryBible(
        hook="宿舍守则第七条是空白的",
        core="不安",
        protagonist_id="c1",
        characters=[Character(id="c1", name="林", role="protagonist")],
    )
    card = SceneCard(scene_id="sc-01", title="守则", genre_beats={"rules": ["熄灯后别应门"]})

    def respond(messages: list[dict[str, str]], model: type[BaseModel]) -> BaseModel | None:
        if model is Canon:
            return Canon(title="守则", story=story)
        if model is SceneDeck:
            return SceneDeck(scenes=[card, card.model_copy(update={"genre_beats": {"x": ["丢"]}})])
        return None

    client = FakeLLMClient(responder=respond)
    run_plan(
        "ghost",
        "宿舍守则",
        client,
        KeywordJudge({}),
        root=tmp_path,
        scenes=2,
        personas=[Persona(id="p")],
        genre="test-ghost",
    )
    directory = tmp_path / "projects" / "ghost"
    assert load_genre_id(directory) == "test-ghost"
    systems = [call["messages"][0]["content"] for call in client.calls]
    assert any("怪谈架构师" in text for text in systems)
    assert any("怪谈总编剧" in text for text in systems)
    assert not any("网文悬疑的总编剧" in text for text in systems)
    cards = load_cards(directory)
    assert cards[0].genre_beats == {"rules": ["熄灯后别应门"]}
    assert cards[1].genre_beats == {}
    assert cards[0].tension_target == pytest.approx(0.9)


def test_genre_beats_are_visible_and_leak_checked() -> None:
    secret = "宿管就是第七条"
    canon = Canon(secrets=[Secret(id="S-1", title="宿管", text=secret)])
    card = SceneCard(scene_id="sc-01", genre_beats={"rules": ["熄灯后别应门"]})
    view = build_writer_view(BookState(canon=canon), card)
    assert view.scene.genre_beats == {"rules": ["熄灯后别应门"]}
    assert "genre_beats" in view.model_dump_json()

    leaky = card.model_copy(update={"genre_beats": {"rules": [f"暗示{secret}"]}})
    with pytest.raises(SecretLeakError):
        build_writer_view(BookState(canon=canon), leaky)
    scrubbed = scrub_secret_text([leaky], canon)[0]
    assert secret not in str(scrubbed.genre_beats)


def test_empty_genre_beats_stay_out_of_the_prompt() -> None:
    view = build_writer_view(BookState(canon=Canon()), SceneCard(scene_id="sc-01"))
    assert "genre_beats" not in view.model_dump_json()


def test_genre_gate_list_and_tiers_drive_the_scene() -> None:
    def respond(messages: list[dict[str, str]], model: type[BaseModel]) -> BaseModel | None:
        if model is Prose:
            return Prose(text="灯灭了。\n有人敲门。\n门开了。")
        if model is ReaderReport:
            return ReaderReport(persona_id="p", tension="high")
        return None

    result = run_scene(
        BookState(canon=Canon()),
        SceneCard(scene_id="sc-01", length=12, pace="steady"),
        ["sc-01"],
        FakeLLMClient(responder=respond),
        KeywordJudge({}),
        [Persona(id="p")],
        genre=GHOST,
    )
    assert result["status"] == "locked"
    assert [r.gate_id for r in result["pre_gate_results"]] == ["literal", "directive"]
    main = {r.gate_id: r for r in result["main_gate_results"]}
    assert set(main) == {"inference", "reveal", "test-rule"}
    assert not main["test-rule"].passed and not main["test-rule"].blocking
    assert result["book"].gate_stats["test-rule"].failures >= 1


def test_custom_gates_name_their_prompt() -> None:
    assert prompt_for_gate("test-rule") == "planner"
    assert prompt_for_gate("hooks") == "planner"
    assert prompt_for_gate("unknown") == "writer"


def test_a_gate_id_cannot_be_taken_twice() -> None:
    with pytest.raises(ValueError, match="already registered"):
        register_gate(GateSpec("test-rule", "main", lambda context: None))
