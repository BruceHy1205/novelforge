"""Offline plan → write path. No network, no human questionnaires."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from pydantic import BaseModel

from novelforge.graph.checkpoint import sqlite_checkpointer
from novelforge.llm.fake import FakeLLMClient
from novelforge.pacing.pace import REVERSAL_DIRECTIVE
from novelforge.pipeline import rollback, run_plan, run_scene, run_write
from novelforge.roles.directives import screen_directives
from novelforge.roles.guess_judge import KeywordJudge
from novelforge.roles.planner import scrub_secret_text
from novelforge.roles.prose import Prose, SceneDeck
from novelforge.schema.canon import Canon, RevealPlanItem, Secret
from novelforge.schema.reader import Persona, ReaderGuess, ReaderReport, SkipSpan
from novelforge.schema.scene import LockedScene, SceneCard
from novelforge.schema.state import BookState
from novelforge.store import load_book, load_canon, load_cards, save_book

CANON = Canon(
    title="雾",
    premise="渡口封了。",
    secrets=[Secret(id="S-1", title="身份", text="账房周先生", probe_question="谁最不对劲？")],
    reveal_plan=[RevealPlanItem(secret_id="S-1", earliest_scene_id="sc-02", method="withhold")],
)
CARDS = [
    SceneCard(scene_id="sc-01", length=4, tension_target=0.3, directives=["他擦了两次杯子。"]),
    SceneCard(scene_id="sc-02", length=4, tension_target=0.3, directives=["灯灭了。"]),
]
PERSONA = Persona(id="p", name="普通读者")
SECRET = "账房周先生"


def _pace_and_length(messages: list[dict[str, str]]) -> tuple[str, int]:
    decoder = json.JSONDecoder()
    for message in reversed(messages):
        content = message["content"].lstrip()
        if not content.startswith("{"):
            continue
        data, _ = decoder.raw_decode(content)
        scene = data.get("scene", data)
        return str(scene.get("pace", "steady")), int(scene.get("length", 4))
    return "steady", 4


def shaped_prose(pace: str, length: int) -> str:
    if pace == "sprint":
        line = "他推开门"
        return "\n".join([line] * max(1, round(length / 4)))
    if pace == "tight":
        line = "他把杯子放下"
        return "\n".join([line] * max(1, round(length / 6)))
    if pace == "slack" and length >= 80:
        half = max(1, length // 2)
        return ("雨" * half) + "\n" + ("雨" * (length - half))
    return "雨" * max(length, 1)


def _client(leaky_first_draft: bool = False) -> FakeLLMClient:
    drafts = {"n": 0}

    def respond(messages: list[dict[str, str]], model: type[BaseModel]) -> BaseModel | None:
        name = model.__name__
        if name == "Canon":
            return CANON
        if name == "SceneDeck":
            return SceneDeck(scenes=CARDS)
        if name == "Prose":
            drafts["n"] += 1
            if leaky_first_draft and drafts["n"] == 1:
                return Prose(text=SECRET)
            pace, length = _pace_and_length(messages)
            return Prose(text=shaped_prose(pace, length))
        if name == "ReaderReport":
            return ReaderReport(persona_id="p", tension="high")
        return None

    return FakeLLMClient(responder=respond)


def test_plan_and_write_lock_scenes_without_leaking_to_the_writer(tmp_path: Path) -> None:
    client = _client()
    judge = KeywordJudge({"S-1": [SECRET]})
    run_plan("demo", "渡口", client, judge, root=tmp_path, scenes=2, personas=[PERSONA])
    assert load_canon(tmp_path / "projects" / "demo").title == "雾"
    assert [card.scene_id for card in load_cards(tmp_path / "projects" / "demo")] == [
        "sc-01",
        "sc-02",
    ]

    database = tmp_path / "projects" / "demo" / "checkpoints.sqlite"
    with sqlite_checkpointer(str(database)) as checkpointer:
        book = run_write(
            "demo", client, judge, root=tmp_path, personas=[PERSONA], checkpointer=checkpointer
        )
    assert [scene.scene_id for scene in book.locked_scenes] == ["sc-01", "sc-02"]
    assert SECRET not in book.locked_scenes[0].text
    manuscript = (tmp_path / "projects" / "demo" / "manuscript" / "book.md").read_text(
        encoding="utf-8"
    )
    assert "## sc-02" in manuscript

    writer_inputs = [
        message["content"]
        for call in client.calls
        if call["role"] == "writer"
        for message in call["messages"]
    ]
    assert writer_inputs
    assert all(SECRET not in text for text in writer_inputs)


def test_literal_leak_is_revised_before_lock(tmp_path: Path) -> None:
    client = _client(leaky_first_draft=True)
    judge = KeywordJudge({"S-1": [SECRET]})
    run_plan("demo", "渡口", client, judge, root=tmp_path, scenes=2, personas=[PERSONA])
    book = run_write("demo", client, judge, root=tmp_path, personas=[PERSONA])
    assert SECRET not in book.locked_scenes[0].text
    first = load_cards(tmp_path / "projects" / "demo")[0]
    assert book.locked_scenes[0].text == shaped_prose(str(first.pace), first.length)


def test_rollback_drops_later_scenes_and_write_can_continue(tmp_path: Path) -> None:
    client = _client()
    judge = KeywordJudge({"S-1": [SECRET]})
    run_plan("demo", "渡口", client, judge, root=tmp_path, scenes=2, personas=[PERSONA])
    database = tmp_path / "projects" / "demo" / "checkpoints.sqlite"
    with sqlite_checkpointer(str(database)) as checkpointer:
        run_write(
            "demo", client, judge, root=tmp_path, personas=[PERSONA], checkpointer=checkpointer
        )
        restored = rollback("demo", "sc-02", root=tmp_path, checkpointer=checkpointer)
    assert [scene.scene_id for scene in restored.locked_scenes] == ["sc-01"]

    with sqlite_checkpointer(str(database)) as checkpointer:
        again = run_write(
            "demo", client, judge, root=tmp_path, personas=[PERSONA], checkpointer=checkpointer
        )
    assert [scene.scene_id for scene in again.locked_scenes] == ["sc-01", "sc-02"]
    assert load_book(tmp_path / "projects" / "demo") is not None


def test_leaking_directive_is_dropped() -> None:
    canon = CANON
    card = SceneCard(scene_id="sc-01", directives=[f"{SECRET}当晚在场"])

    def respond(_messages: list[dict[str, str]], model: type[BaseModel]) -> Any:
        if model.__name__ == "SceneDeck":
            return SceneDeck(scenes=[card])
        if model.__name__ == "ReaderReport":
            return ReaderReport(
                persona_id="p",
                guesses=[ReaderGuess(probe_id="S-1", guess=SECRET, confidence="certain")],
            )
        return None

    screened = screen_directives(
        card, canon, [PERSONA], FakeLLMClient(responder=respond), KeywordJudge({"S-1": [SECRET]})
    )
    assert screened.directives == []


def test_scrub_keeps_a_planned_reveal_and_strips_hidden_answers() -> None:
    cards = scrub_secret_text(
        [
            SceneCard(
                scene_id="sc-01",
                title="关于 S-1",
                beat_purpose=f"点明{SECRET}",
                ending_hook=SECRET,
                directives=[f"{SECRET}当晚在场"],
            ),
            SceneCard(
                scene_id="sc-02",
                must_reveal=["S-1"],
                directives=[f"说清楚：{SECRET}"],
            ),
        ],
        CANON,
    )
    assert SECRET not in cards[0].beat_purpose
    assert "S-1" not in cards[0].title
    assert cards[0].directives == []
    assert SECRET not in cards[0].ending_hook
    assert cards[1].directives == [f"说清楚：{SECRET}"]


def test_missing_ending_hook_is_rewritten_into_the_scene() -> None:
    def respond(messages: list[dict[str, str]], model: type[BaseModel]) -> BaseModel | None:
        if model.__name__ != "Prose":
            if model.__name__ == "ReaderReport":
                return ReaderReport(persona_id="p", tension="high", wants_to_know=["然后呢"])
            return None
        if "当前正文" in messages[-1]["content"]:
            return Prose(text="雨一直下门开了")
        return Prose(text="雨一直下啊啊")

    result = run_scene(
        BookState(canon=CANON),
        SceneCard(scene_id="sc-01", length=8, tension_target=0.3, ending_hook="门开了"),
        ["sc-01", "sc-02"],
        FakeLLMClient(responder=respond),
        KeywordJudge({"S-1": [SECRET]}),
        [PERSONA],
    )
    assert result["status"] == "locked"
    assert "门开了" in result["locked"].text


def test_skim_tightens_the_rewrite() -> None:
    readers = {"n": 0}

    def respond(messages: list[dict[str, str]], model: type[BaseModel]) -> BaseModel | None:
        name = model.__name__
        if name == "Prose":
            if "当前正文" in messages[-1]["content"]:
                pace, length = _pace_and_length(messages)
                return Prose(text=shaped_prose(pace, length))
            return Prose(text="甲\n乙\n丙\n丁")
        if name == "ReaderReport":
            readers["n"] += 1
            if readers["n"] == 1:
                return ReaderReport(
                    persona_id="p",
                    tension="high",
                    skip_spans=[SkipSpan(scene_id="sc-01", paragraph_start=0, paragraph_end=1)],
                )
            return ReaderReport(persona_id="p", tension="high")
        return None

    result = run_scene(
        BookState(canon=CANON),
        SceneCard(scene_id="sc-01", length=4, tension_target=0.3, pace="steady"),
        ["sc-01"],
        FakeLLMClient(responder=respond),
        KeywordJudge({"S-1": [SECRET]}),
        [PERSONA],
    )
    assert result["status"] == "locked"
    assert result["locked"].text.startswith("他把杯子放下")
    assert readers["n"] >= 2


def test_two_flat_scenes_force_a_reversal_on_the_next(tmp_path: Path) -> None:
    deck = [SceneCard(scene_id=f"sc-0{index}", tension_target=0.3) for index in range(1, 4)]

    def respond(messages: list[dict[str, str]], model: type[BaseModel]) -> BaseModel | None:
        name = model.__name__
        if name == "Canon":
            return CANON
        if name == "SceneDeck":
            return SceneDeck(scenes=deck)
        if name == "Prose":
            pace, length = _pace_and_length(messages)
            return Prose(text=shaped_prose(pace, length))
        if name == "ReaderReport":
            return ReaderReport(persona_id="p", tension="high")
        return None

    client = FakeLLMClient(responder=respond)
    judge = KeywordJudge({"S-1": [SECRET]})
    run_plan("demo", "渡口", client, judge, root=tmp_path, scenes=3, personas=[PERSONA])
    directory = tmp_path / "projects" / "demo"
    book = load_book(directory)
    assert book is not None
    seeded = book.model_copy(
        update={
            "locked_scenes": [
                LockedScene.lock("sc-01", "甲"),
                LockedScene.lock("sc-02", "乙"),
            ],
            "tension_trace": [0.1, 0.1],
        }
    )
    save_book(directory, seeded)
    written = run_write("demo", client, judge, root=tmp_path, personas=[PERSONA])
    assert [scene.scene_id for scene in written.locked_scenes] == ["sc-01", "sc-02", "sc-03"]
    writer_inputs = [
        message["content"]
        for call in client.calls
        if call["role"] == "writer"
        for message in call["messages"]
        if "sc-03" in message["content"]
    ]
    assert writer_inputs
    assert any(REVERSAL_DIRECTIVE in text for text in writer_inputs)
    assert any("0.95" in text for text in writer_inputs)
