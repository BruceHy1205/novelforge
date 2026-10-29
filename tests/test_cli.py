from __future__ import annotations

from pathlib import Path

import yaml
from typer.testing import CliRunner

from novelforge import __version__
from novelforge.cli import app
from novelforge.llm.routing import ROLES, ModelRouting
from novelforge.schema.canon import Canon

runner = CliRunner()


def test_version() -> None:
    result = runner.invoke(app, ["version"])
    assert result.exit_code == 0
    assert result.stdout.strip() == __version__


def test_init_demo_writes_empty_canon(tmp_path: Path) -> None:
    result = runner.invoke(app, ["init", "demo", "--path", str(tmp_path)])
    assert result.exit_code == 0
    canon_path = tmp_path / "projects" / "demo" / "canon.yaml"
    assert canon_path.is_file()
    loaded = yaml.safe_load(canon_path.read_text(encoding="utf-8"))
    canon = Canon.model_validate(loaded)
    assert canon.secrets == []
    assert canon.reveal_plan == []
    assert canon.title == ""
    assert canon.premise == ""

    project = tmp_path / "projects" / "demo"
    assert (project / "scenes").is_dir()
    assert (project / "manuscript").is_dir()
    routing = ModelRouting.load(project / "models.yaml")
    assert set(routing.roles) == set(ROLES)


def test_init_demo_refuses_overwrite(tmp_path: Path) -> None:
    runner.invoke(app, ["init", "demo", "--path", str(tmp_path)])
    result = runner.invoke(app, ["init", "demo", "--path", str(tmp_path)])
    assert result.exit_code == 1


def test_plan_fake_shuangwen_refuses_an_empty_canon(tmp_path: Path) -> None:
    result = runner.invoke(
        app,
        [
            "plan",
            "empty",
            "废灵根",
            "--path",
            str(tmp_path),
            "--fake",
            "--genre",
            "shuangwen",
            "--scenes",
            "2",
        ],
    )
    assert result.exit_code == 1
    assert "没有主角" in result.output
    directory = tmp_path / "projects" / "empty"
    assert (directory / "idea.txt").is_file()
    assert not (directory / "canon.yaml").is_file()
    assert not list((directory / "scenes").glob("sc-*.yaml"))


def test_plan_help_shows_scenes_per_batch() -> None:
    result = runner.invoke(app, ["plan", "--help"])
    assert result.exit_code == 0
    assert "--scenes-per-batch" in result.stdout
    assert "default: 3" in result.stdout
    rejected = runner.invoke(
        app,
        ["plan", "demo", "雨", "--scenes-per-batch", "0", "--fake"],
    )
    assert rejected.exit_code != 0


def test_plan_forwards_scenes_per_batch(tmp_path: Path, monkeypatch) -> None:
    seen: dict[str, int] = {}

    def fake_run_plan(*_args, **kwargs):
        seen["scenes_per_batch"] = kwargs["scenes_per_batch"]
        return tmp_path

    monkeypatch.setattr("novelforge.cli.run_plan", fake_run_plan)
    omitted = runner.invoke(app, ["plan", "demo", "雨", "--path", str(tmp_path), "--fake"])
    assert omitted.exit_code == 0
    assert seen["scenes_per_batch"] == 3
    explicit = runner.invoke(
        app,
        ["plan", "demo", "雨", "--path", str(tmp_path), "--fake", "--scenes-per-batch", "1"],
    )
    assert explicit.exit_code == 0
    assert seen["scenes_per_batch"] == 1


def test_doctor_offline() -> None:
    result = runner.invoke(app, ["doctor"])
    assert result.exit_code == 0
    assert "doctor: ok" in result.stdout
    assert "no-op" in result.stdout
