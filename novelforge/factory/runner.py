"""Run one factory step on a book's project directory through the normal pipeline."""

from __future__ import annotations

import os
import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from novelforge.genres import get_genre
from novelforge.llm.routing import default_routing_yaml
from novelforge.pipeline import cast_pov, rollback, run_plan, run_write
from novelforge.project import create_project
from novelforge.roles.clues import build_clues
from novelforge.roles.memory import note_review
from novelforge.schema.state import BookState
from novelforge.store import (
    load_book,
    load_canon,
    load_cards,
    project_dir,
    save_book,
    save_genre_id,
)


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


def outline(
    root: Path,
    slug: str,
    idea: str,
    genre: str,
    chapters: int,
    dry_run: bool,
    keep_canon: bool = False,
    keep_outline: bool = False,
) -> str:
    """Plan canon and scene cards. Returns the book title.

    Topic books leave both keep flags off: the project directory is replaced
    so the outline is a fresh read of the idea. `models.yaml` is copied back
    when it was already there. `keep_canon` reuses `canon.yaml` and still
    plans cards. `keep_outline` reuses canon and scene cards and does not
    call the architect or the planner.
    """

    directory = project_dir(slug, root)
    if keep_canon or keep_outline:
        return _outline_kept(root, slug, idea, genre, chapters, dry_run, keep_outline=keep_outline)
    preserved_models = _text_if_file(directory / "models.yaml")
    if directory.exists():
        shutil.rmtree(directory)
    create_project(slug, root=root, genre=genre)
    if preserved_models is not None:
        (directory / "models.yaml").write_text(preserved_models, encoding="utf-8")
    runtime = runtime_for(directory, genre, dry_run)
    run_plan(slug, idea, runtime.client, runtime.judge, root=root, scenes=chapters, genre=genre)
    return load_canon(directory).title


def _text_if_file(path: Path) -> str | None:
    if path.is_file():
        return path.read_text(encoding="utf-8")
    return None


def _outline_kept(
    root: Path,
    slug: str,
    idea: str,
    genre: str,
    chapters: int,
    dry_run: bool,
    *,
    keep_outline: bool,
) -> str:
    directory = project_dir(slug, root)
    if not directory.exists():
        raise RuntimeError("keep_canon / keep_outline 需要已有项目目录，不能另起一本")
    (directory / "scenes").mkdir(parents=True, exist_ok=True)
    (directory / "manuscript").mkdir(parents=True, exist_ok=True)
    save_genre_id(directory, genre)
    if not (directory / "models.yaml").is_file():
        (directory / "models.yaml").write_text(default_routing_yaml(), encoding="utf-8")
    if keep_outline:
        if not (directory / "canon.yaml").is_file() or not load_cards(directory):
            raise RuntimeError("keep_outline 需要已有 canon.yaml 和场景卡")
        sync_book_state(directory)
        return load_canon(directory).title
    if not (directory / "canon.yaml").is_file():
        raise RuntimeError("keep_canon 需要已有 canon.yaml")
    runtime = runtime_for(directory, genre, dry_run)
    run_plan(
        slug,
        idea,
        runtime.client,
        runtime.judge,
        root=root,
        scenes=chapters,
        keep_canon=True,
        freeze_canon=True,
        genre=genre,
    )
    return load_canon(directory).title


def sync_book_state(directory: Path) -> None:
    """Point book state at the injected canon and cards without dropping locked chapters."""

    canon = load_canon(directory)
    cards = load_cards(directory)
    if not cards:
        raise RuntimeError("没有场景卡")
    existing = load_book(directory)
    if existing is not None and existing.locked_scenes:
        save_book(directory, existing.model_copy(update={"canon": canon}))
        return
    book = note_review(
        BookState(canon=canon, clues=build_clues(cards, canon), pov_states=cast_pov(canon)),
        "canon",
    )
    save_book(directory, book)


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
