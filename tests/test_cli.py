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


def test_doctor_offline() -> None:
    result = runner.invoke(app, ["doctor"])
    assert result.exit_code == 0
    assert "doctor: ok" in result.stdout
    assert "no-op" in result.stdout
