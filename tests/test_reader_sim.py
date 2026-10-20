from __future__ import annotations

import pytest

from novelforge.llm.fake import FakeLLMClient
from novelforge.roles.reader_sim import UnsafeProbeError, probes_from_canon, simulate_reader
from novelforge.schema.canon import Canon, Secret
from novelforge.schema.reader import Persona, ReaderGuess, ReaderProbe, ReaderReport, SkipSpan
from novelforge.schema.scene import LockedScene


def _manuscript() -> list[LockedScene]:
    return [
        LockedScene.lock("sc-01", "The harbor was empty."),
        LockedScene.lock("sc-02", "Someone had moved the lantern."),
    ]


def test_simulate_reader_empty_report_with_fake_client() -> None:
    report = simulate_reader(_manuscript(), Persona(id="p-skimmer"))
    assert report.persona_id == "p-skimmer"
    assert report.last_scene_id == "sc-02"
    assert report.guesses == []
    assert report.skip_spans == []


def test_simulate_reader_sends_only_manuscript_and_probes() -> None:
    client = FakeLLMClient(defaults={"persona_id": "p-1"})
    canon = Canon(
        secrets=[
            Secret(id="S-1", title="t", text="The butler did it.", probe_question="谁是凶手？")
        ]
    )
    simulate_reader(_manuscript(), Persona(id="p-1"), probes_from_canon(canon), client=client)

    call = client.calls[0]
    sent = "".join(message["content"] for message in call["messages"])
    assert call["role"] == "reader_sim"
    assert "Someone had moved the lantern." in sent
    assert "谁是凶手？" in sent
    assert "The butler did it." not in sent


def test_simulate_reader_sanitizes_model_output() -> None:
    probes = [
        ReaderProbe(probe_id="S-1", question="谁？"),
        ReaderProbe(probe_id="S-2", question="为何？"),
    ]
    canned = ReaderReport(
        persona_id="someone-else",
        last_scene_id="sc-99",
        guesses=[
            ReaderGuess(probe_id="S-1", guess="the butler", confidence="suspect"),
            ReaderGuess(probe_id="S-1", guess="duplicate", confidence="certain"),
            ReaderGuess(probe_id="S-9", guess="not asked", confidence="certain"),
        ],
        skip_spans=[
            SkipSpan(scene_id="sc-02", paragraph_start=0, paragraph_end=0),
            SkipSpan(scene_id="sc-02", paragraph_start=5, paragraph_end=6),
            SkipSpan(scene_id="sc-01", paragraph_start=0, paragraph_end=0),
        ],
    )
    report = simulate_reader(
        _manuscript(),
        Persona(id="p-1"),
        probes,
        client=FakeLLMClient(canned={ReaderReport: canned}),
    )
    assert report.persona_id == "p-1"
    assert report.last_scene_id == "sc-02"
    assert [(g.probe_id, g.guess, g.confidence) for g in report.guesses] == [
        ("S-1", "the butler", "suspect"),
        ("S-2", "", "none"),
    ]
    assert report.skip_spans == [SkipSpan(scene_id="sc-02", paragraph_start=0, paragraph_end=0)]


def test_prompt_numbers_paragraphs_and_marks_latest_scene() -> None:
    client = FakeLLMClient()
    manuscript = [
        LockedScene.lock("sc-01", "第一段\n\n第二段"),
        LockedScene.lock("sc-02", "第三段"),
    ]
    simulate_reader(manuscript, Persona(id="p", name="推理迷"), client=client)
    system, user = (m["content"] for m in client.calls[0]["messages"])
    assert "推理迷" in system
    assert "[¶0] 第一段\n[¶1] 第二段" in user
    assert "场景 sc-02（最新一场）" in user
    assert user.rstrip().endswith("最新一场：sc-02")
    assert client.calls[0]["scene_id"] == "sc-02"


def test_probes_skip_revealed_and_reject_leaky_questions() -> None:
    canon = Canon(
        secrets=[
            Secret(id="S-1", title="t1", text="butler", probe_question="谁是凶手？"),
            Secret(id="S-2", title="t2", text="twin", probe_question="谁在灯塔？"),
        ]
    )
    assert [p.probe_id for p in probes_from_canon(canon, revealed={"S-2"})] == ["S-1"]

    leaky = Canon(
        secrets=[Secret(id="S-1", title="t", text="butler", probe_question="是 butler 吗？")]
    )
    with pytest.raises(UnsafeProbeError):
        probes_from_canon(leaky)
