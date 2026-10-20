from __future__ import annotations

import json
from pathlib import Path

import yaml
from typer.testing import CliRunner

from novelforge.cli import app
from novelforge.eval.calibration import data_path, load_story
from novelforge.eval.calibration.schema import HumanResponseSet
from novelforge.eval.contamination import ContaminationAnswer, check_contamination
from novelforge.llm.fake import FakeLLMClient
from novelforge.roles.guess_judge import KeywordJudge

runner = CliRunner()
STORY = data_path("example") / "story.yaml"
RESPONSES = data_path("example") / "responses"


def test_questionnaire_is_prefilled(tmp_path: Path) -> None:
    out = tmp_path / "r09.yaml"
    result = runner.invoke(
        app, ["eval", "questionnaire", str(STORY), "--reader", "r09", "--out", str(out)]
    )
    assert result.exit_code == 0, result.output
    filled = HumanResponseSet.model_validate(yaml.safe_load(out.read_text(encoding="utf-8")))
    assert filled.reader_id == "r09"
    assert [r.scene_id for r in filled.responses] == ["sc-01", "sc-02", "sc-03", "sc-04"]
    assert [g.probe_id for g in filled.responses[0].guesses] == ["S-1"]
    assert [g.probe_id for g in filled.responses[1].guesses] == ["S-1", "S-2"]
    assert filled.responses[1].guesses[1].question == "林伯和周先生是什么关系？"


def test_calibrate_fake_dry_run_writes_report(tmp_path: Path) -> None:
    out = tmp_path / "report.json"
    result = runner.invoke(
        app,
        [
            "eval",
            "calibrate",
            str(STORY),
            "--responses",
            str(RESPONSES),
            "--fake",
            "--resamples",
            "20",
            "--out",
            str(out),
        ],
    )
    assert result.exit_code == 0, result.output
    assert "exit criteria: FAIL" in result.stdout
    report = json.loads(out.read_text(encoding="utf-8"))
    assert report["personas"] == ["mystery_fan", "casual", "impatient"]
    assert report["pooled"]["miss_rate"] == 1.0


def test_calibrate_repeats_reports_the_range(tmp_path: Path) -> None:
    out = tmp_path / "report.json"
    result = runner.invoke(
        app,
        [
            "eval",
            "calibrate",
            str(STORY),
            "--responses",
            str(RESPONSES),
            "--fake",
            "--repeats",
            "2",
            "--resamples",
            "5",
            "--out",
            str(out),
        ],
    )
    assert result.exit_code == 0, result.output
    assert "repeats 2" in result.stdout
    assert "exit criteria: FAIL" in result.stdout
    report = json.loads(out.read_text(encoding="utf-8"))
    assert report["repeats"] == 2
    assert report["miss_rate"]["low"] == report["miss_rate"]["high"] == 1.0


def test_contamination_flags_known_story() -> None:
    story = load_story(STORY)
    client = FakeLLMClient(
        canned={ContaminationAnswer: ContaminationAnswer(knows_story=True, answer="周先生")}
    )
    results = {
        r.secret_id: r for r in check_contamination(story, client, KeywordJudge(story.keywords()))
    }
    assert results["S-1"].contaminated
    assert not results["S-2"].contaminated
    prompt = client.calls[0]["messages"][0]["content"]
    assert story.title in prompt
    assert story.scenes[1].text.splitlines()[0] not in prompt


def test_contamination_cli_clean_with_fake() -> None:
    result = runner.invoke(app, ["eval", "contamination", str(STORY), "--fake"])
    assert result.exit_code == 0, result.output
    assert "clean" in result.stdout
