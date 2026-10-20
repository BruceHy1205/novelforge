"""P5: chapter memory, summary packets, cheap screening, and gate frequency."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
from pydantic import BaseModel

from novelforge.llm.fake import FakeLLMClient
from novelforge.pipeline import run_plan, run_scene
from novelforge.roles.memory import (
    apply_memory,
    archive_closed,
    format_gate_report,
    is_opening_scene,
    reading_packet,
)
from novelforge.roles.prose import Prose
from novelforge.roles.reader_sim import simulate_reader
from novelforge.schema.canon import Canon, Secret
from novelforge.schema.memory import ChapterSummary, GateStat
from novelforge.schema.reader import Persona, ReaderReport, ReaderState
from novelforge.schema.scene import LockedScene, SceneCard
from novelforge.schema.state import BookState
from novelforge.store import load_book
from novelforge.view.filter import SecretLeakError, build_writer_view

SECRET = "账房周先生"
CANON = Canon(
    secrets=[Secret(id="S-1", title="身份", text=SECRET, probe_question="谁最不对劲？")],
)


def test_reading_packet_keeps_recent_scenes_and_scrubs_old_summaries() -> None:
    scenes = [LockedScene.lock(f"sc-0{index}", f"独特句子{index}") for index in range(1, 7)]
    summary = ChapterSummary(
        chapter_id="ch-01",
        scene_ids=["sc-01", "sc-02", "sc-03"],
        text=f"前三场{SECRET}下了雨",
    )
    packet = reading_packet(scenes, [summary], [SECRET])
    assert packet[0].scene_id == "mem-ch-01"
    assert SECRET not in packet[0].text
    assert "前三场" in packet[0].text
    assert [scene.scene_id for scene in packet[1:]] == ["sc-04", "sc-05", "sc-06"]
    assert "独特句子1" not in "\n".join(scene.text for scene in packet)
    assert reading_packet(scenes[:2], [summary]) == scenes[:2]


def test_reader_prompt_labels_a_summary_and_the_latest_scene() -> None:
    client = FakeLLMClient()
    packet = [
        LockedScene.lock("mem-ch-01", "前三场下了雨"),
        LockedScene.lock("sc-04", "他把杯子放下"),
        LockedScene.lock("sc-05", "灯灭了"),
        LockedScene.lock("sc-06", "门开了"),
    ]
    simulate_reader(packet, Persona(id="p"), client=client)
    user = client.calls[0]["messages"][1]["content"]
    assert "前文摘要 mem-ch-01" in user
    assert "场景 sc-06（最新一场）" in user
    assert client.calls[0]["role"] == "reader_sim"


def test_chapter_summary_drops_hidden_text_and_does_not_repeat() -> None:
    scenes = [
        LockedScene.lock("sc-01", f"他看见{SECRET}"),
        LockedScene.lock("sc-02", "他把杯子放下"),
        LockedScene.lock("sc-03", "灯灭了"),
    ]
    book = apply_memory(BookState(canon=CANON, locked_scenes=scenes), FakeLLMClient())
    assert [summary.chapter_id for summary in book.summaries] == ["ch-01"]
    assert SECRET not in book.summaries[0].text
    assert "他把杯子放下" in book.summaries[0].text
    again = apply_memory(book, FakeLLMClient())
    assert again.summaries == book.summaries


def test_closed_questions_leave_the_writer_view() -> None:
    previous = {"p": ReaderState(persona_id="p", open_questions=["灯为什么灭了", "还在问"])}
    current = {"p": ReaderState(persona_id="p", open_questions=["还在问"])}
    archived = archive_closed(previous, current, [])
    assert archived == ["灯为什么灭了"]
    book = BookState(
        canon=CANON,
        reader_states=current,
        archived_questions=archived,
    )
    view = build_writer_view(book, SceneCard(scene_id="sc-02"))
    blob = view.model_dump_json()
    assert "还在问" in blob
    assert "灯为什么灭了" not in blob


def test_a_summary_cannot_smuggle_a_secret_into_the_writer_view() -> None:
    book = BookState(
        canon=CANON,
        summaries=[ChapterSummary(chapter_id="ch-01", scene_ids=["sc-01"], text=SECRET)],
    )
    with pytest.raises(SecretLeakError):
        build_writer_view(book, SceneCard(scene_id="sc-02"))


def test_opening_window_is_the_first_three_chapters() -> None:
    assert is_opening_scene(0) is True
    assert is_opening_scene(8) is True
    assert is_opening_scene(9) is False


def test_gate_report_names_the_prompt_to_change() -> None:
    book = BookState(
        reader_sim_calls=4,
        gate_stats={
            "style": GateStat(checks=3, failures=2),
            "length": GateStat(checks=3, failures=0),
        },
    )
    lines = format_gate_report(book)
    assert "读者模拟器调用 4 次" in lines
    assert "先改 writer：style 失败最多" in lines


def test_cheap_gates_block_the_reader_simulator() -> None:
    def respond(_messages: list[dict[str, str]], model: type[BaseModel]) -> Any:
        if model.__name__ == "Prose":
            return Prose(text=SECRET)
        return None

    client = FakeLLMClient(responder=respond)
    result = run_scene(
        BookState(canon=CANON),
        SceneCard(scene_id="sc-01", length=8, pace="steady"),
        ["sc-01"],
        client,
        _judge(),
        [Persona(id="p")],
    )
    assert result["status"] == "escalated"
    assert result["book"].reader_sim_calls == 0
    assert result["book"].gate_stats["literal"].failures >= 1
    assert all(call["role"] != "reader_sim" for call in client.calls)


def test_a_cause_is_cut_before_the_reader_simulator_runs() -> None:
    def respond(_messages: list[dict[str, str]], model: type[BaseModel]) -> Any:
        name = model.__name__
        if name == "Prose":
            return Prose(text="他回头看了一眼")
        if name == "ReaderReport":
            return ReaderReport(persona_id="p", tension="high")
        return None

    client = FakeLLMClient(responder=respond)
    result = run_scene(
        BookState(canon=CANON),
        SceneCard(
            scene_id="sc-01",
            length=8,
            pace="steady",
            tension_target=0.3,
            directives=["他离开，因为有人在看"],
        ),
        ["sc-01"],
        client,
        _judge(),
        [Persona(id="p")],
    )
    roles = [call["role"] for call in client.calls]
    assert result["status"] == "locked"
    assert roles[0] == "writer"
    assert roles[1] == "reviser"
    assert "reader_sim" not in roles[:2]
    assert result["book"].gate_stats["directive"].failures >= 1
    assert result["book"].reader_sim_calls == 1
    assert any(mark.kind == "opening" for mark in result["book"].review_marks)


def test_payoff_and_replan_are_recorded_without_stopping(tmp_path: Path) -> None:
    def respond(_messages: list[dict[str, str]], model: type[BaseModel]) -> Any:
        name = model.__name__
        if name == "Prose":
            return Prose(text="灯为什么灭了，他回头看了一眼")
        if name == "ReaderReport":
            return ReaderReport(persona_id="p", tension="high", wants_to_know=["门后是谁"])
        return None

    result = run_scene(
        BookState(
            canon=CANON,
            reader_states={"p": ReaderState(persona_id="p", open_questions=["灯为什么灭了"])},
        ),
        SceneCard(
            scene_id="sc-01",
            length=13,
            pace="steady",
            tension_target=0.3,
            must_reveal=["S-1"],
        ),
        ["sc-01"],
        FakeLLMClient(responder=respond),
        _judge(),
        [Persona(id="p")],
    )
    kinds = {mark.kind for mark in result["book"].review_marks}
    assert result["status"] == "locked"
    assert "payoff" in kinds
    assert "opening" in kinds
    assert result["book"].archived_questions == ["灯为什么灭了"]

    planner = FakeLLMClient(canned={Canon: CANON})
    run_plan("demo", "渡口", planner, _judge(), root=tmp_path, scenes=2, personas=[])
    planned = load_book(tmp_path / "projects" / "demo")
    assert planned is not None
    assert any(mark.kind == "canon" for mark in planned.review_marks)


def _judge() -> Any:
    from novelforge.roles.guess_judge import KeywordJudge

    return KeywordJudge({"S-1": [SECRET]})
