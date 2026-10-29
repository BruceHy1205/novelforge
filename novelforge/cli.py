"""Typer CLI: init / version / doctor / plan / write / serve / eval."""

from __future__ import annotations

import importlib.metadata
import sys
from pathlib import Path
from typing import Annotated, Any

import typer

from novelforge import __version__
from novelforge.eval_cli import eval_app
from novelforge.genres import DEFAULT_GENRE, GenreError, genre_ids, get_genre
from novelforge.pipeline import rollback, run_baseline, run_plan, run_write
from novelforge.project import create_project
from novelforge.roles.guess_judge import KeywordJudge, LLMGuessJudge
from novelforge.roles.memory import format_gate_report
from novelforge.roles.planner import PLAN_BATCH

app = typer.Typer(
    name="novelforge",
    help="Canon-isolated AI long-form novel production.",
    no_args_is_help=True,
)
app.add_typer(eval_app, name="eval")


@app.command()
def init(
    name: Annotated[str, typer.Argument(help="Project directory name under projects/")],
    path: Annotated[
        Path | None,
        typer.Option("--path", help="Workspace root (defaults to the current directory)."),
    ] = None,
    genre: Annotated[
        str, typer.Option("--genre", help="Rule set (see `novelforge genres`)")
    ] = DEFAULT_GENRE,
) -> None:
    """Create projects/<name> with canon.yaml, models.yaml, scenes/, manuscript/."""

    _check_genre(genre)
    try:
        project_dir = create_project(name, root=path, genre=genre)
    except FileExistsError as exc:
        typer.echo(str(exc), err=True)
        raise typer.Exit(code=1) from exc
    typer.echo(f"created {project_dir}")


def _check_genre(genre: str | None) -> None:
    if genre is None:
        return
    try:
        get_genre(genre)
    except GenreError as exc:
        typer.echo(str(exc), err=True)
        raise typer.Exit(code=1) from exc


@app.command()
def genres() -> None:
    """List the genre rule sets."""

    for genre_id in genre_ids():
        mark = " (default)" if genre_id == DEFAULT_GENRE else ""
        typer.echo(f"{genre_id:<12}{get_genre(genre_id).name}{mark}")


@app.command()
def version() -> None:
    """Print the installed package version."""

    typer.echo(__version__)


@app.command()
def doctor() -> None:
    """Check the local toolchain. Does not open network connections."""

    ok = True
    typer.echo(f"python          {sys.version.split()[0]}")

    # Use package metadata — importing litellm can open the network.
    required = (
        ("pydantic", "pydantic"),
        ("typer", "typer"),
        ("pyyaml", "yaml"),
        ("litellm", "litellm"),
        ("instructor", "instructor"),
        ("langgraph", "langgraph"),
    )
    for dist_name, label in required:
        try:
            typer.echo(f"{label:<16}{importlib.metadata.version(dist_name)}")
        except importlib.metadata.PackageNotFoundError:
            typer.echo(f"{label:<16}FAIL (not installed)")
            ok = False

    from novelforge.observability import langfuse_enabled

    try:
        langfuse_version = importlib.metadata.version("langfuse")
        status = "ok" if langfuse_enabled() else "ok (no keys — no-op)"
        typer.echo(f"{'langfuse':<16}{status} {langfuse_version}")
    except importlib.metadata.PackageNotFoundError:
        typer.echo("langfuse        optional (not installed; no-op)")

    from novelforge.llm.routing import ModelRouting

    provider = ModelRouting().provider
    typer.echo(f"{'model api':<16}{provider.api_base or 'litellm default'}")
    if provider.api_key_env:
        import os

        key_status = "set" if os.environ.get(provider.api_key_env) else "MISSING"
        typer.echo(f"{'model key':<16}{provider.api_key_env} {key_status}")

    typer.echo("embeddings      unwired (G1 uses character bigrams, not bge-m3)")

    if not ok:
        raise typer.Exit(code=1)
    typer.echo("doctor: ok")


def _runtime(name: str, path: Path | None, fake: bool, genre: str | None = None) -> tuple[Any, Any]:
    from novelforge.llm.client import LiteLLMClient
    from novelforge.llm.fake import FakeLLMClient
    from novelforge.llm.routing import ModelRouting
    from novelforge.store import load_genre_id, project_dir

    if fake:
        return FakeLLMClient(), KeywordJudge({})
    directory = project_dir(name, path)
    models = directory / "models.yaml"
    routing = ModelRouting.load(models) if models.is_file() else ModelRouting()
    client = LiteLLMClient(routing)
    return client, LLMGuessJudge(client, get_genre(genre or load_genre_id(directory)))


@app.command()
def plan(
    name: Annotated[str, typer.Argument(help="Project name under projects/")],
    idea: Annotated[str, typer.Argument(help="Story idea")],
    path: Annotated[Path | None, typer.Option("--path", help="Workspace root")] = None,
    scenes: Annotated[int, typer.Option(help="How many scenes to plan")] = 8,
    fake: Annotated[bool, typer.Option("--fake", help="Offline empty models")] = False,
    keep_canon: Annotated[
        bool, typer.Option("--keep-canon", help="Reuse the saved canon.yaml; only plan scenes")
    ] = False,
    genre: Annotated[
        str | None,
        typer.Option("--genre", help="Rule set; saved to project.yaml (default: the saved one)"),
    ] = None,
    scenes_per_batch: Annotated[
        int,
        typer.Option(
            "--scenes-per-batch",
            min=1,
            help="Scene cards written by each planner call",
        ),
    ] = PLAN_BATCH,
) -> None:
    """Write canon.yaml and scenes/sc-*.yaml from an idea."""

    from novelforge.roles.audit import PlanRejected

    _check_genre(genre)
    client, judge = _runtime(name, path, fake, genre)
    try:
        directory = run_plan(
            name,
            idea,
            client,
            judge,
            root=path,
            scenes=scenes,
            keep_canon=keep_canon,
            genre=genre,
            scenes_per_batch=scenes_per_batch,
        )
    except PlanRejected as exc:
        typer.echo(str(exc), err=True)
        raise typer.Exit(code=1) from exc
    typer.echo(f"planned {directory}")


@app.command()
def write(
    name: Annotated[str, typer.Argument(help="Project name under projects/")],
    path: Annotated[Path | None, typer.Option("--path", help="Workspace root")] = None,
    fake: Annotated[bool, typer.Option("--fake", help="Offline empty models")] = False,
    drafts: Annotated[
        int, typer.Option(help="Candidate drafts per chapter; the critic picks one")
    ] = 2,
    limit: Annotated[
        int | None, typer.Option(help="Stop after this many chapters (default: all)")
    ] = None,
) -> None:
    """Write manuscript/book.md. Resumes from the Sqlite checkpoint and state.yaml."""

    from novelforge.graph.checkpoint import sqlite_checkpointer
    from novelforge.store import project_dir

    client, judge = _runtime(name, path, fake)
    directory = project_dir(name, path)
    with sqlite_checkpointer(str(directory / "checkpoints.sqlite")) as checkpointer:
        book = run_write(
            name,
            client,
            judge,
            root=path,
            checkpointer=checkpointer,
            drafts=drafts,
            limit=limit,
        )
    typer.echo(f"locked {len(book.locked_scenes)} scenes")


@app.command()
def baseline(
    name: Annotated[str, typer.Argument(help="Project name under projects/")],
    idea: Annotated[str, typer.Argument(help="Story idea")],
    path: Annotated[Path | None, typer.Option("--path", help="Workspace root")] = None,
    scenes: Annotated[int, typer.Option(help="Scene count to ask for")] = 8,
    fake: Annotated[bool, typer.Option("--fake", help="Offline empty models")] = False,
) -> None:
    """Write manuscript/baseline.md in one call, with no Canon and no gates."""

    client, _judge = _runtime(name, path, fake)
    target = run_baseline(name, idea, client, root=path, scenes=scenes)
    typer.echo(f"wrote {target}")


@app.command()
def rollback_scene(
    name: Annotated[str, typer.Argument(help="Project name under projects/")],
    scene_id: Annotated[str, typer.Argument(help="Scene to redo, e.g. sc-02")],
    path: Annotated[Path | None, typer.Option("--path", help="Workspace root")] = None,
) -> None:
    """Drop a scene and everything after it, using the snapshot taken before that scene."""

    from novelforge.graph.checkpoint import sqlite_checkpointer
    from novelforge.store import project_dir

    directory = project_dir(name, path)
    database = directory / "checkpoints.sqlite"
    if database.is_file():
        with sqlite_checkpointer(str(database)) as checkpointer:
            book = rollback(name, scene_id, root=path, checkpointer=checkpointer)
    else:
        book = rollback(name, scene_id, root=path)
    typer.echo(f"restored {len(book.locked_scenes)} locked scenes")


@app.command()
def gates(
    name: Annotated[str, typer.Argument(help="Project name under projects/")],
    path: Annotated[Path | None, typer.Option("--path", help="Workspace root")] = None,
) -> None:
    """Print gate checks, failures, and which prompt to change. Does not stop a write."""

    from novelforge.store import load_book, project_dir

    book = load_book(project_dir(name, path))
    if book is None:
        typer.echo("还没有 state.yaml", err=True)
        raise typer.Exit(code=1)
    for line in format_gate_report(book):
        typer.echo(line)


@app.command()
def serve(
    root: Annotated[
        Path, typer.Option("--root", help="Factory directory: factory.sqlite and projects/")
    ] = Path("factory"),
    host: Annotated[str, typer.Option(help="Bind address")] = "127.0.0.1",
    port: Annotated[int, typer.Option(help="Port")] = 8765,
) -> None:
    """Open the batch console. The factory starts paused; press 开始 to produce."""

    import uvicorn

    from novelforge.factory.service import Factory
    from novelforge.web.app import create_app

    typer.echo(f"NovelForge 批量生产台：http://{host}:{port}  （工厂目录 {root.resolve()}）")
    uvicorn.run(create_app(Factory(root)), host=host, port=port, log_level="warning")


if __name__ == "__main__":
    app()
