"""Run one factory step on a book's project directory through the normal pipeline."""

from __future__ import annotations

import os
import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from novelforge.genres import get_genre
from novelforge.pipeline import rollback, run_plan, run_write
from novelforge.project import create_project
from novelforge.store import load_book, load_canon, load_cards, project_dir


@dataclass(frozen=True)
class Runtime:
    client: Any
    judge: Any


def live_runtime(directory: Path, genre: str) -> Runtime:
    from novelforge.llm.client import LiteLLMClient
    from novelforge.llm.routing import ModelRouting
    from novelforge.roles.guess_judge import LLMGuessJudge

    models = directory / "models.yaml"
    routing = ModelRouting.load(models) if models.is_file() else ModelRouting()
    env = routing.provider.api_key_env
    if env and not os.environ.get(env):
        raise RuntimeError(f"环境变量 {env} 没有设置，无法调用模型")
    client = LiteLLMClient(routing)
    return Runtime(client, LLMGuessJudge(client, get_genre(genre)))


def dry_runtime() -> Runtime:
    from novelforge.factory.dryrun import dry_run_client
    from novelforge.roles.guess_judge import KeywordJudge

    return Runtime(dry_run_client(), KeywordJudge({}))


def runtime_for(directory: Path, genre: str, dry_run: bool) -> Runtime:
    return dry_runtime() if dry_run else live_runtime(directory, genre)


def outline(root: Path, slug: str, idea: str, genre: str, chapters: int, dry_run: bool) -> str:
    """Plan canon and every chapter card from scratch. Returns the book title."""

    directory = project_dir(slug, root)
    if directory.exists():
        shutil.rmtree(directory)
    create_project(slug, root=root, genre=genre)
    runtime = runtime_for(directory, genre, dry_run)
    run_plan(slug, idea, runtime.client, runtime.judge, root=root, scenes=chapters, genre=genre)
    return load_canon(directory).title


def write_upto(root: Path, slug: str, genre: str, upto: int, drafts: int, dry_run: bool) -> int:
    """Write until `upto` chapters are locked. Already locked chapters are skipped."""

    directory = project_dir(slug, root)
    runtime = runtime_for(directory, genre, dry_run)
    book = run_write(slug, runtime.client, runtime.judge, root=root, drafts=drafts, limit=upto)
    return len(book.locked_scenes)


def locked_count(root: Path, slug: str) -> int:
    book = load_book(project_dir(slug, root))
    return 0 if book is None else len(book.locked_scenes)


def card_count(root: Path, slug: str) -> int:
    return len(load_cards(project_dir(slug, root)))


def restart_writing(root: Path, slug: str) -> None:
    """Drop every locked chapter so the trial is written again from the outline."""

    directory = project_dir(slug, root)
    cards = load_cards(directory)
    if cards and (directory / "snapshots" / f"{cards[0].scene_id}.yaml").is_file():
        rollback(slug, cards[0].scene_id, root=root)


def remove(root: Path, slug: str) -> None:
    directory = project_dir(slug, root)
    if slug and directory.exists():
        shutil.rmtree(directory)
