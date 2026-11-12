"""Persist a caller-supplied brief and enqueue it on the factory.

The creative system owns the idea, Canon, and scene cards. This module
validates them, writes the project files, and marks the book so the outline
worker does not invent a replacement or delete the directory.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from sqlmodel import Session, select

from novelforge.factory.models import (
    BUSY,
    FULL_QUEUED,
    QUEUED,
    STAGES,
    TRASHED,
    TRIAL_QUEUED,
    Book,
)
from novelforge.factory.runner import sync_book_state
from novelforge.factory.service import Factory, FactoryError
from novelforge.genres import DEFAULT_GENRE, GenreError, get_genre
from novelforge.llm.routing import ModelRouting, default_routing_yaml
from novelforge.roles.architect import structural_problems
from novelforge.schema.canon import Canon
from novelforge.schema.scene import SceneCard
from novelforge.store import load_canon, load_cards, project_dir, save_cards, save_genre_id
from novelforge.store import save_canon as save_canon_yaml

_SCENE_ID = re.compile(r"^sc-\d{2,}$")
_ENV_NAME = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
_SECRET_KEYS = frozenset({"api_key", "apikey", "api_secret", "access_token", "authorization"})

STAGE_FOR = {"outline": QUEUED, "trial": TRIAL_QUEUED, "full": FULL_QUEUED}
RUN_LABEL = {"outline": "进入大纲队列", "trial": "进入试读队列", "full": "进入全书队列"}


@dataclass(frozen=True)
class RunRequest:
    stage: str = "outline"
    keep_canon: bool | None = None
    keep_outline: bool | None = None
    keep_cards: bool | None = None
    trial_chapters: int | None = None
    stop_at: int | None = None


@dataclass(frozen=True)
class Brief:
    external_id: str | None = None
    genre: str | None = None
    idea: str = ""
    core: str = ""
    chapters: int | None = None
    canon: Canon | None = None
    cards: list[SceneCard] | None = None
    models: ModelRouting | None = None
    run: RunRequest | None = None


def create_book(factory: Factory, brief: Brief) -> tuple[Book, bool]:
    """Insert a book, or return the one already stored under `external_id`."""

    with factory.lock:
        external_id = _clean_external_id(brief.external_id)
        existing = _find(factory, external_id) if external_id else None
        if existing is not None:
            _reject_busy(existing)
        created = existing is None
        genre = _resolve_genre(brief.genre, existing.genre if existing else None)
        _validate_assets(genre, brief.canon, brief.cards, brief.models)
        idea = derive_idea(brief.idea, brief.core, brief.canon)
        if brief.cards is not None and brief.canon is None and created:
            raise FactoryError("写入大纲时需要同时提供 canon")
        if (
            brief.chapters is not None
            and brief.cards is not None
            and brief.chapters != len(brief.cards)
        ):
            raise FactoryError(
                f"chapters 是 {brief.chapters}，但大纲有 {len(brief.cards)} 张场景卡"
            )
        if created and brief.canon is None and not brief.cards and not idea:
            raise FactoryError("需要 idea、core 或 canon")
        if created:
            book = _insert(factory, genre, idea, _chapter_count(brief), external_id)
        else:
            assert existing is not None and existing.id is not None
            book = existing
        book = _apply(factory, book, brief, genre, idea)
        if created and book.id is not None:
            factory.log(book.id, "创意入库")
        if brief.run is not None and book.id is not None:
            book = enqueue(factory, book.id, brief.run)
        return book, created


def save_canon(factory: Factory, book_id: int, canon: Canon) -> Book:
    with factory.lock:
        book = _editable(factory, book_id)
        _check_canon(canon, book.genre)
        directory = ensure_dir(factory.root, book.slug, book.genre)
        save_canon_yaml(directory, canon)
        idea = book.idea or derive_idea("", "", canon)
        if idea:
            (directory / "idea.txt").write_text(idea.strip() + "\n", encoding="utf-8")
        fields: dict[str, Any] = {"keep_canon": True, "idea": idea or book.idea}
        if not book.keep_outline:
            fields["mode"] = "keep_canon"
        if canon.title:
            fields["title"] = canon.title
        if book.keep_outline and load_cards(directory):
            sync_book_state(directory)
        saved = _save(factory, book_id, **fields)
        factory.log(book_id, "写入 Canon，跳过架构师")
        return saved


def save_outline(factory: Factory, book_id: int, cards: list[SceneCard]) -> Book:
    with factory.lock:
        book = _editable(factory, book_id)
        _check_cards(cards)
        directory = project_dir(book.slug, factory.root)
        if not (directory / "canon.yaml").is_file():
            raise FactoryError("写入大纲前需要 canon")
        _check_canon(load_canon(directory), book.genre)
        ensure_dir(factory.root, book.slug, book.genre)
        replace_cards(directory, cards)
        sync_book_state(directory)
        saved = _save(
            factory,
            book_id,
            keep_canon=True,
            keep_outline=True,
            mode="keep_outline",
            chapters=len(cards),
        )
        factory.log(book_id, "写入大纲，跳过规划器")
        return saved


def save_models(factory: Factory, book_id: int, routing: ModelRouting) -> Book:
    with factory.lock:
        book = _editable(factory, book_id)
        check_routing(routing)
        directory = ensure_dir(factory.root, book.slug, book.genre)
        write_routing(directory, routing)
        factory.log(book_id, "更新模型路由")
        return book


def enqueue(factory: Factory, book_id: int, spec: RunRequest) -> Book:
    """Move the book onto a factory queue. Files must already be in place."""

    if spec.stage not in STAGE_FOR:
        raise FactoryError("stage 只能是 outline、trial 或 full")
    with factory.lock:
        book = _editable(factory, book_id)
        if book.stage == TRASHED:
            raise FactoryError("回收站里的书要先恢复")
        fields = _run_fields(book, spec)
        _require_ready(
            factory,
            book,
            spec.stage,
            keep_canon=bool(fields["keep_canon"]),
            keep_outline=bool(fields["keep_outline"]),
        )
        target = STAGE_FOR[spec.stage]
        allowed = [stage for stage in STAGES if stage not in BUSY and stage != TRASHED]
        return factory._move(book_id, allowed, target, RUN_LABEL[spec.stage], **fields)


def derive_idea(idea: str, core: str, canon: Canon | None) -> str:
    """A one-string idea for the old pipeline. Canon stays the source of truth."""

    supplied = idea.strip()
    feeling = core.strip()
    if supplied:
        if feeling and feeling not in supplied:
            return f"{feeling}\n\n{supplied}"
        return supplied
    parts: list[str] = []
    if feeling:
        parts.append(feeling)
    if canon is not None:
        story = canon.story
        for bit in (
            canon.title,
            canon.premise,
            story.hook,
            story.selling_point,
            story.core,
            story.background,
            story.concept,
        ):
            text = bit.strip()
            if text and text not in parts:
                parts.append(text)
    return "\n\n".join(parts)


def ensure_dir(root: Path, slug: str, genre: str) -> Path:
    """Project folder without inventing a Canon. An existing canon.yaml is left alone."""

    directory = project_dir(slug, root)
    directory.mkdir(parents=True, exist_ok=True)
    (directory / "scenes").mkdir(exist_ok=True)
    (directory / "manuscript").mkdir(exist_ok=True)
    if not (directory / "models.yaml").is_file():
        (directory / "models.yaml").write_text(default_routing_yaml(), encoding="utf-8")
    save_genre_id(directory, genre)
    return directory


def replace_cards(directory: Path, cards: list[SceneCard]) -> None:
    scenes = directory / "scenes"
    scenes.mkdir(parents=True, exist_ok=True)
    names = {f"{card.scene_id}.yaml" for card in cards}
    for path in list(scenes.glob("sc-*.yaml")):
        if path.name not in names:
            path.unlink()
    save_cards(directory, cards)


def check_routing(routing: ModelRouting) -> None:
    env = routing.provider.api_key_env
    if env is not None and not _ENV_NAME.match(env):
        raise FactoryError("provider.api_key_env 只能是环境变量名，密钥留在环境里")
    _reject_secret_keys(routing.model_dump(mode="json"))


def write_routing(directory: Path, routing: ModelRouting) -> None:
    check_routing(routing)
    header = (
        "# Role routing only. The API key is read from provider.api_key_env.\n"
        "# Do not put a key in this file.\n"
    )
    (directory / "models.yaml").write_text(header + routing.to_yaml(), encoding="utf-8")


def _apply(factory: Factory, book: Book, brief: Brief, genre: str, idea: str) -> Book:
    assert book.id is not None
    if brief.cards is not None and brief.canon is None:
        directory = project_dir(book.slug, factory.root)
        if not (directory / "canon.yaml").is_file():
            raise FactoryError("写入大纲前需要 canon")
        _check_canon(load_canon(directory), genre)
    fields: dict[str, Any] = {}
    if genre != book.genre:
        fields["genre"] = genre
    if idea and idea != book.idea:
        fields["idea"] = idea
    chapters = len(brief.cards) if brief.cards is not None else brief.chapters
    if chapters is not None and chapters != book.chapters:
        fields["chapters"] = chapters
    keep_canon = book.keep_canon
    keep_outline = book.keep_outline
    mode = book.mode
    if brief.canon is not None:
        keep_canon = True
        if not keep_outline:
            mode = "keep_canon"
        if brief.canon.title:
            fields["title"] = brief.canon.title
    if brief.cards is not None:
        keep_outline = True
        keep_canon = True
        mode = "keep_outline"
    if mode != book.mode:
        fields["mode"] = mode
    if keep_canon != book.keep_canon:
        fields["keep_canon"] = keep_canon
    if keep_outline != book.keep_outline:
        fields["keep_outline"] = keep_outline

    directory = project_dir(book.slug, factory.root)
    if brief.canon is not None or brief.cards is not None or brief.models is not None:
        directory = ensure_dir(factory.root, book.slug, genre)
    if brief.canon is not None:
        save_canon_yaml(directory, brief.canon)
        factory.log(book.id, "写入 Canon，跳过架构师")
    if brief.cards is not None:
        replace_cards(directory, brief.cards)
        factory.log(book.id, "写入大纲，跳过规划器")
    if brief.models is not None:
        write_routing(directory, brief.models)
        factory.log(book.id, "更新模型路由")
    if idea and directory.exists():
        (directory / "idea.txt").write_text(idea.strip() + "\n", encoding="utf-8")
    if keep_outline and (directory / "canon.yaml").is_file() and load_cards(directory):
        sync_book_state(directory)
    if fields:
        return _save(factory, book.id, **fields)
    return book


def _run_fields(book: Book, spec: RunRequest) -> dict[str, Any]:
    keep_canon = book.keep_canon
    keep_outline = book.keep_outline
    if spec.keep_canon is True:
        keep_canon = True
    if spec.keep_outline is True or spec.keep_cards is True:
        keep_outline = True
        keep_canon = True
    if keep_outline:
        mode = "keep_outline"
    elif keep_canon:
        mode = "keep_canon"
    else:
        mode = book.mode or "plan_from_idea"
    fields: dict[str, Any] = {
        "keep_canon": keep_canon,
        "keep_outline": keep_outline,
        "mode": mode,
        "enqueued": True,
        "error": "",
        "prev_stage": "",
    }
    if spec.trial_chapters is not None:
        fields["trial_chapters"] = spec.trial_chapters
    if spec.stop_at is not None:
        fields["stop_at"] = spec.stop_at
    return fields


def _require_ready(
    factory: Factory,
    book: Book,
    stage: str,
    *,
    keep_canon: bool,
    keep_outline: bool,
) -> None:
    directory = project_dir(book.slug, factory.root)
    cards = load_cards(directory) if directory.exists() else []
    needs_canon = keep_canon or keep_outline or stage in ("trial", "full")
    if stage in ("trial", "full") and not cards:
        raise FactoryError("还没有大纲，不能进入试读或全书")
    if keep_outline and not cards:
        raise FactoryError("keep_outline 需要已写入场景卡")
    if needs_canon and not (directory / "canon.yaml").is_file():
        raise FactoryError("还没有 Canon")
    if needs_canon:
        _check_canon(load_canon(directory), book.genre)
    if stage in ("trial", "full"):
        sync_book_state(directory)


def _validate_assets(
    genre: str,
    canon: Canon | None,
    cards: list[SceneCard] | None,
    routing: ModelRouting | None,
) -> None:
    if canon is not None:
        _check_canon(canon, genre)
    if cards is not None:
        _check_cards(cards)
    if routing is not None:
        check_routing(routing)


def _check_canon(canon: Canon, genre: str) -> None:
    problems = structural_problems(canon, get_genre(genre))
    if problems:
        raise FactoryError("；".join(problems))


def _check_cards(cards: list[SceneCard]) -> None:
    if not cards:
        raise FactoryError("大纲至少需要一张场景卡")
    ids = [card.scene_id for card in cards]
    bad = [scene_id for scene_id in ids if not _SCENE_ID.match(scene_id)]
    if bad:
        raise FactoryError("scene_id 要用 sc-01 这种编号：" + "、".join(bad))
    if len(set(ids)) != len(ids):
        raise FactoryError("scene_id 重复")


def _reject_secret_keys(data: object) -> None:
    if isinstance(data, dict):
        for key, value in data.items():
            if str(key).lower().replace("-", "_") in _SECRET_KEYS:
                raise FactoryError(f"{key} 不能写入接口，密钥只放在环境变量里")
            _reject_secret_keys(value)
    elif isinstance(data, list):
        for item in data:
            _reject_secret_keys(item)


def _resolve_genre(requested: str | None, current: str | None) -> str:
    genre = requested or current or DEFAULT_GENRE
    try:
        get_genre(genre)
    except GenreError as exc:
        raise FactoryError(str(exc)) from exc
    return genre


def _chapter_count(brief: Brief) -> int:
    if brief.cards:
        return len(brief.cards)
    if brief.chapters is not None:
        return brief.chapters
    return 20


def _clean_external_id(value: str | None) -> str | None:
    if value is None:
        return None
    text = value.strip()
    if not text:
        return None
    if len(text) > 200:
        raise FactoryError("external_id 太长")
    return text


def _reject_busy(book: Book) -> None:
    if book.stage in BUSY:
        raise FactoryError("这本书正在写，等这一步结束再改")


def _editable(factory: Factory, book_id: int) -> Book:
    book = factory.book(book_id)
    _reject_busy(book)
    return book


def _find(factory: Factory, external_id: str) -> Book | None:
    with Session(factory.engine) as session:
        return session.exec(select(Book).where(Book.external_id == external_id)).first()


def _insert(
    factory: Factory,
    genre: str,
    idea: str,
    chapters: int,
    external_id: str | None,
) -> Book:
    with Session(factory.engine) as session:
        book = Book(
            genre=genre,
            idea=idea,
            chapters=chapters,
            stage=QUEUED,
            enqueued=False,
            mode="plan_from_idea",
            external_id=external_id,
            created_at=factory.clock(),
            updated_at=factory.clock(),
        )
        session.add(book)
        session.flush()
        book.slug = f"book-{book.id:04d}"
        session.add(book)
        session.commit()
        session.refresh(book)
        return book


def _save(factory: Factory, book_id: int, **fields: Any) -> Book:
    with Session(factory.engine) as session:
        book = session.get(Book, book_id)
        if book is None:
            raise KeyError(book_id)
        for key, value in fields.items():
            setattr(book, key, value)
        book.updated_at = factory.clock()
        session.add(book)
        session.commit()
        session.refresh(book)
        return book
