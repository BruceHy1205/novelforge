"""End-to-end calibration on the bundled synthetic example, with scripted simulators."""

from __future__ import annotations

import re
from collections.abc import Callable

import pytest
from pydantic import BaseModel

from novelforge.eval.calibrate import aggregate_reports, run_calibration, run_repeats
from novelforge.eval.calibration import data_path, load_personas, load_responses, load_story
from novelforge.eval.calibration.schema import CalibrationStory
from novelforge.llm.fake import FakeLLMClient
from novelforge.roles.guess_judge import KeywordJudge
from novelforge.schema.reader import ReaderGuess, ReaderReport, SkipSpan

EXAMPLE = data_path("example")

Script = dict[str, list[tuple[str, str, str]]]

# Mirrors the synthetic human majority scene by scene.
FAITHFUL: Script = {
    "sc-01": [],
    "sc-02": [("S-1", "周先生", "suspect")],
    "sc-03": [("S-1", "周先生", "certain"), ("S-2", "兄弟", "hint")],
}
# Claims certainty about the right answer from the very first scene.
OVERCONFIDENT: Script = {
    scene: [("S-1", "周先生", "certain"), ("S-2", "兄弟", "certain")]
    for scene in ("sc-01", "sc-02", "sc-03", "sc-04")
}
# Never catches on.
OBLIVIOUS: Script = {}


def _responder(script: Script) -> Callable[[list[dict[str, str]], type[BaseModel]], BaseModel]:
    def respond(messages: list[dict[str, str]], _model: type[BaseModel]) -> BaseModel:
        latest = re.search(r"最新一场：(\S+)", messages[-1]["content"]).group(1)  # type: ignore[union-attr]
        impatient = "没耐心" in messages[0]["content"]
        skips = (
            [SkipSpan(scene_id=latest, paragraph_start=3, paragraph_end=3)]
            if impatient and latest in {"sc-02", "sc-03"}
            else []
        )
        return ReaderReport(
            persona_id="ignored",
            guesses=[
                ReaderGuess(probe_id=pid, guess=guess, confidence=conf)  # type: ignore[arg-type]
                for pid, guess, conf in script.get(latest, [])
            ],
            skip_spans=skips,
        )

    return respond


def _run(script: Script, readers: list[str] | None = None):
    story = load_story(EXAMPLE / "story.yaml")
    responses = load_responses(EXAMPLE / "responses")
    if readers is not None:
        responses = [r for r in responses if r.reader_id in readers]
    return run_calibration(
        [story],
        responses,
        load_personas(data_path("personas.yaml")),
        FakeLLMClient(responder=_responder(script)),
        KeywordJudge(story.keywords()),
        resamples=50,
    )


def test_example_story_loads_and_reveal_scene_is_excluded() -> None:
    story = load_story(EXAMPLE / "story.yaml")
    assert isinstance(story, CalibrationStory)
    assert not story.is_scored("sc-04", story.secrets[0])
    assert not story.is_scored("sc-01", story.secrets[1])  # asked only from sc-02
    report = _run(FAITHFUL)
    assert report.pooled.n_cells == 5
    assert report.pooled.n_readers == 3


def test_probes_are_only_asked_from_ask_from_scene() -> None:
    story = load_story(EXAMPLE / "story.yaml")
    client = FakeLLMClient(responder=_responder(FAITHFUL))
    run_calibration(
        [story],
        [],
        load_personas(data_path("personas.yaml"))[:1],
        client,
        KeywordJudge(story.keywords()),
        resamples=1,
        workers=1,
    )
    asked = {
        re.search(r"最新一场：(\S+)", call["messages"][-1]["content"]).group(1): call["messages"][
            -1
        ]["content"]
        for call in client.calls
    }
    assert "S-2:" not in asked["sc-01"]
    assert "S-2:" in asked["sc-02"]


def test_ask_from_must_precede_reveal() -> None:
    data = load_story(EXAMPLE / "story.yaml").model_dump()
    data["secrets"][1]["ask_from"] = "sc-04"
    with pytest.raises(ValueError, match="ask_from"):
        CalibrationStory.model_validate(data)


def test_faithful_simulator_passes() -> None:
    pooled = _run(FAITHFUL).pooled
    assert pooled.spearman_ensemble == pytest.approx(1.0)
    assert pooled.miss_rate == 0.0
    assert pooled.false_alarm_rate == 0.0
    assert pooled.human_ceiling is not None
    assert pooled.exit.passed, pooled.exit


def test_overconfident_simulator_fails_on_false_alarms() -> None:
    pooled = _run(OVERCONFIDENT).pooled
    assert pooled.miss_rate == 0.0
    assert pooled.false_alarm_rate == pytest.approx(1.0)
    assert pooled.exit.miss_ok
    assert not pooled.exit.false_alarm_ok
    assert not pooled.exit.passed


def test_oblivious_simulator_fails_on_misses() -> None:
    pooled = _run(OBLIVIOUS).pooled
    timing = next(t for t in pooled.timings if t.secret_id == "S-1")
    assert timing.human_scene == "sc-02"
    assert timing.missed is True
    assert pooled.miss_rate == 1.0
    assert not pooled.exit.passed


def test_skip_overlap_against_human_majority() -> None:
    overlap = _run(FAITHFUL).pooled.skip_overlap_by_persona
    assert overlap["impatient"] == pytest.approx(1.0)
    assert overlap["casual"] == 0.0


def test_ceiling_needs_two_readers() -> None:
    pooled = _run(FAITHFUL, readers=["r01"]).pooled
    assert pooled.human_ceiling is None
    assert any("ceiling" in note for note in pooled.exit.notes)


def test_reports_are_kept_per_persona_and_scene() -> None:
    report = _run(FAITHFUL)
    reports = report.sim_reports["example-lighthouse"]["mystery_fan"]
    assert [r.last_scene_id for r in reports] == ["sc-01", "sc-02", "sc-03", "sc-04"]
    assert reports[0].persona_id == "mystery_fan"


def test_identical_repeats_stay_stable_and_pass() -> None:
    story = load_story(EXAMPLE / "story.yaml")
    report = run_repeats(
        [story],
        load_responses(EXAMPLE / "responses"),
        load_personas(data_path("personas.yaml")),
        FakeLLMClient(responder=_responder(FAITHFUL)),
        KeywordJudge(story.keywords()),
        repeats=3,
        resamples=20,
        workers=2,
    )
    assert report.repeats == 3
    assert report.spearman_ensemble.low == report.spearman_ensemble.high == 1.0
    assert report.miss_rate.high == 0.0
    assert report.false_alarm_rate.high == 0.0
    assert all(timing.stable for timing in report.timings)
    assert report.exit.passed


def test_a_repeat_that_crosses_the_threshold_fails_even_if_the_mean_is_close() -> None:
    faithful = _run(FAITHFUL)
    overconfident = _run(OVERCONFIDENT)
    summary = aggregate_reports([faithful, overconfident])
    assert summary.false_alarm_rate.mean == pytest.approx(0.5)
    assert summary.false_alarm_rate.high == pytest.approx(1.0)
    assert not summary.exit.passed
    s1 = next(item for item in summary.timings if item.secret_id == "S-1")
    assert not s1.stable

    dipped = faithful.model_copy(deep=True)
    dipped.pooled.spearman_ensemble = 0.4
    spread = aggregate_reports([faithful, dipped])
    assert spread.spearman_ensemble.mean == pytest.approx(0.7)
    assert spread.spearman_ensemble.low == pytest.approx(0.4)
    assert not spread.exit.spearman_ok
    assert any("crosses target" in note for note in spread.exit.notes)


def test_human_pre_marked_correct_overrides_judge() -> None:
    story = load_story(EXAMPLE / "story.yaml")
    responses = load_responses(EXAMPLE / "responses")
    r03 = next(r for r in responses if r.reader_id == "r03")
    guess = r03.responses[1].guesses[0]  # sc-02, "老板娘": the keyword judge says wrong
    guess.confidence = "suspect"
    guess.correct = True
    report = run_calibration(
        [story],
        [r03],
        [],
        FakeLLMClient(),
        KeywordJudge(story.keywords()),
        resamples=10,
    )
    timing = next(t for t in report.pooled.timings if t.secret_id == "S-1")
    assert timing.human_scene == "sc-02"
