"""Batch production: keep the queue topped up, respect the backlogs, wait for reviews.

One scheduler thread wakes every few seconds (or when something changes), purges
expired trash, adds books from enabled topics while fewer than `max_total` are
unfinished, and hands queued work to a thread pool. Downstream work goes first,
so a freshly approved outline or trial is picked up before any new outline.

The factory starts paused. Nothing calls a model until `start()`.
"""

from __future__ import annotations

import threading
import traceback
from collections.abc import Callable, Iterable
from concurrent.futures import Future, ThreadPoolExecutor
from datetime import datetime, timedelta
from pathlib import Path
from types import ModuleType
from typing import Any

from sqlalchemy import func
from sqlmodel import Session, SQLModel, col, create_engine, select

from novelforge.factory import runner as default_runner
from novelforge.factory.models import (
    BUSY,
    DONE,
    FAILED,
    FINISHED,
    FULL_QUEUED,
    FULL_WRITING,
    OUTLINE_BACKLOG,
    OUTLINE_REVIEW,
    OUTLINING,
    QUEUED,
    STAGES,
    TRASHED,
    TRIAL_BACKLOG,
    TRIAL_QUEUED,
    TRIAL_REVIEW,
    TRIAL_WRITING,
    Book,
    Event,
    Settings,
    Topic,
    now,
)

TICK_SECONDS = 3.0
MAX_WORKERS = 16


class FactoryError(ValueError):
    """An action that does not apply to the book's current stage."""


class Factory:
    def __init__(
        self,
        root: Path,
        *,
        runner: ModuleType | Any = default_runner,
        clock: Callable[[], datetime] = now,
    ) -> None:
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)
        self.runner = runner
        self.clock = clock
        self.engine = create_engine(
            f"sqlite:///{self.root / 'factory.sqlite'}",
            connect_args={"check_same_thread": False},
        )
        SQLModel.metadata.create_all(self.engine)
        self.lock = threading.RLock()
        self.running = False
        self.jobs: dict[int, Future[None]] = {}
        self.executor = ThreadPoolExecutor(max_workers=MAX_WORKERS, thread_name_prefix="book")
        self.wake = threading.Event()
        self.closed = threading.Event()
        self.thread: threading.Thread | None = None
        self._recover()

    # lifecycle

    def serve(self) -> None:
        """Run the scheduler loop in a daemon thread."""

        if self.thread is not None:
            return
        self.thread = threading.Thread(target=self._loop, name="factory", daemon=True)
        self.thread.start()

    def close(self, wait: bool = False) -> None:
        self.running = False
        self.closed.set()
        self.wake.set()
        self.executor.shutdown(wait=wait, cancel_futures=True)

    def _loop(self) -> None:
        while not self.closed.is_set():
            try:
                self.tick()
            except Exception:  # noqa: BLE001 - the loop must survive a bad tick
                self.log(None, "调度出错：" + traceback.format_exc(limit=3), "error")
            self.wake.wait(TICK_SECONDS)
            self.wake.clear()

    def start(self) -> None:
        self.running = True
        self.log(None, "开始批量生产")
        self.wake.set()

    def pause(self) -> None:
        self.running = False
        self.log(None, "暂停：正在写的书写完当前一章后回到队列")
        self.wake.set()

    def _recover(self) -> None:
        with Session(self.engine) as session:
            if session.get(Settings, 1) is None:
                session.add(Settings(id=1))
            for book in session.exec(select(Book).where(col(Book.stage).in_(list(BUSY)))):
                book.stage = BUSY[book.stage]
                session.add(book)
            session.commit()

    # settings and topics

    def settings(self) -> Settings:
        with Session(self.engine) as session:
            return session.get(Settings, 1) or Settings(id=1)

    def update_settings(self, changes: dict[str, Any]) -> Settings:
        with self.lock, Session(self.engine) as session:
            current = session.get(Settings, 1) or Settings(id=1)
            merged = Settings.model_validate({**current.model_dump(), **changes, "id": 1})
            for key, value in merged.model_dump().items():
                setattr(current, key, value)
            session.add(current)
            session.commit()
            session.refresh(current)
        self.wake.set()
        return current

    def topics(self) -> list[dict[str, Any]]:
        with Session(self.engine) as session:
            topics = session.exec(select(Topic).order_by(col(Topic.id))).all()
            made = self._topic_counts(session)
            return [
                {**topic.model_dump(), "produced": made.get(topic.id or 0, 0)} for topic in topics
            ]

    def save_topic(self, data: dict[str, Any], topic_id: int | None = None) -> Topic:
        from novelforge.genres import GenreError, get_genre

        with self.lock, Session(self.engine) as session:
            current = session.get(Topic, topic_id) if topic_id is not None else None
            if topic_id is not None and current is None:
                raise KeyError(topic_id)
            base = current.model_dump() if current is not None else {}
            merged = Topic.model_validate({**base, **data, "id": topic_id})
            try:
                get_genre(merged.genre)
            except GenreError as exc:
                raise FactoryError(str(exc)) from exc
            if not merged.name.strip():
                raise FactoryError("题材名称不能为空")
            target = current or merged
            for key, value in merged.model_dump(exclude={"id", "created_at"}).items():
                setattr(target, key, value)
            session.add(target)
            session.commit()
            session.refresh(target)
        self.wake.set()
        return target

    def delete_topic(self, topic_id: int) -> None:
        with self.lock, Session(self.engine) as session:
            topic = session.get(Topic, topic_id)
            if topic is None:
                raise KeyError(topic_id)
            session.delete(topic)
            session.commit()

    @staticmethod
    def _topic_counts(session: Session) -> dict[int, int]:
        rows = session.exec(
            select(Book.topic_id, func.count())
            .where(Book.stage != TRASHED)
            .group_by(col(Book.topic_id))
        ).all()
        return {int(topic_id): int(count) for topic_id, count in rows if topic_id is not None}

    # status

    def counts(self) -> dict[str, int]:
        with Session(self.engine) as session:
            rows = session.exec(select(Book.stage, func.count()).group_by(col(Book.stage))).all()
        found = {stage: 0 for stage in STAGES}
        found.update({stage: int(count) for stage, count in rows})
        return found

    def status(self) -> dict[str, Any]:
        counts = self.counts()
        settings = self.settings()
        return {
            "running": self.running,
            "dry_run": settings.dry_run,
            "counts": counts,
            "active": sum(n for stage, n in counts.items() if stage not in FINISHED),
            "outline_backlog": sum(counts[stage] for stage in OUTLINE_BACKLOG),
            "trial_backlog": sum(counts[stage] for stage in TRIAL_BACKLOG),
            "busy": sorted(self.jobs),
            "settings": settings.model_dump(),
        }

    # books

    def books(self, stages: Iterable[str] | None = None) -> list[Book]:
        with Session(self.engine) as session:
            query = select(Book).order_by(col(Book.id).desc())
            if stages:
                query = query.where(col(Book.stage).in_(list(stages)))
            return list(session.exec(query).all())

    def book(self, book_id: int) -> Book:
        with Session(self.engine) as session:
            book = session.get(Book, book_id)
            if book is None:
                raise KeyError(book_id)
            return book

    def events(self, book_id: int | None = None, limit: int = 100) -> list[Event]:
        with Session(self.engine) as session:
            query = select(Event).order_by(col(Event.id).desc()).limit(limit)
            if book_id is not None:
                query = query.where(Event.book_id == book_id)
            return list(session.exec(query).all())

    def log(self, book_id: int | None, message: str, level: str = "info") -> None:
        with Session(self.engine) as session:
            session.add(Event(book_id=book_id, message=message, level=level, at=self.clock()))
            session.commit()

    def _move(
        self,
        book_id: int,
        allowed: Iterable[str],
        stage: str,
        message: str,
        **fields: Any,
    ) -> Book:
        with self.lock, Session(self.engine) as session:
            book = session.get(Book, book_id)
            if book is None:
                raise KeyError(book_id)
            if book.stage not in allowed:
                raise FactoryError(
                    f"《{book.title or book.slug}》当前阶段是 {book.stage}，不能这样操作"
                )
            book.stage = stage
            book.updated_at = self.clock()
            for key, value in fields.items():
                setattr(book, key, value)
            session.add(book)
            session.commit()
            session.refresh(book)
        self.log(book_id, message)
        self.wake.set()
        return book

    def approve(self, book_id: int, note: str = "") -> Book:
        stage = self.book(book_id).stage
        if stage == OUTLINE_REVIEW:
            return self._move(book_id, [OUTLINE_REVIEW], TRIAL_QUEUED, "大纲审核通过", note=note)
        return self._move(book_id, [TRIAL_REVIEW], FULL_QUEUED, "试读审核通过", note=note)

    def trash(self, book_id: int, note: str = "") -> Book:
        book = self.book(book_id)
        if book.stage == TRASHED:
            return book
        previous = BUSY.get(book.stage, book.stage)
        label = "毙掉，进入回收站" if book.stage in (OUTLINE_REVIEW, TRIAL_REVIEW) else "移入回收站"
        return self._move(
            book_id,
            [stage for stage in STAGES if stage != TRASHED],
            TRASHED,
            label,
            prev_stage=previous,
            trashed_at=self.clock(),
            note=note or book.note,
        )

    def restore(self, book_id: int) -> Book:
        previous = self.book(book_id).prev_stage or QUEUED
        return self._move(
            book_id, [TRASHED], previous, "从回收站恢复", prev_stage="", trashed_at=None
        )

    def retry(self, book_id: int) -> Book:
        previous = self.book(book_id).prev_stage or QUEUED
        return self._move(book_id, [FAILED], previous, "重试", prev_stage="", error="")

    def redo(self, book_id: int) -> Book:
        """Outline review: plan again from the idea. Trial review: rewrite the trial."""

        book = self.book(book_id)
        if book.stage == OUTLINE_REVIEW:
            return self._move(book_id, [OUTLINE_REVIEW], QUEUED, "退回重做大纲", written=0)
        if book.stage == TRIAL_REVIEW:
            self.runner.restart_writing(self.root, book.slug)
            return self._move(book_id, [TRIAL_REVIEW], TRIAL_QUEUED, "退回重写试读", written=0)
        raise FactoryError("只有待审大纲或待审试读可以退回重做")

    def delete(self, book_id: int) -> None:
        with self.lock, Session(self.engine) as session:
            book = session.get(Book, book_id)
            if book is None:
                raise KeyError(book_id)
            if book.stage != TRASHED:
                raise FactoryError("只能永久删除回收站里的书")
            if book_id in self.jobs:
                raise FactoryError("这本书的上一步还在跑，等它停下再删")
            self.runner.remove(self.root, book.slug)
            for event in session.exec(select(Event).where(Event.book_id == book_id)):
                session.delete(event)
            session.delete(book)
            session.commit()

    def empty_trash(self) -> int:
        removed = 0
        for book in self.books([TRASHED]):
            if book.id is not None and book.id not in self.jobs:
                self.delete(book.id)
                removed += 1
        return removed

    def purge(self) -> int:
        """Delete trash older than `trash_days`."""

        cutoff = self.clock() - timedelta(days=self.settings().trash_days)
        removed = 0
        for book in self.books([TRASHED]):
            if book.id is None or book.id in self.jobs:
                continue
            if book.trashed_at is not None and book.trashed_at <= cutoff:
                self.delete(book.id)
                removed += 1
        if removed:
            self.log(None, f"回收站自动清理 {removed} 本（超过 {self.settings().trash_days} 天）")
        return removed

    # scheduling

    def tick(self) -> list[int]:
        """One scheduling pass. Returns the books that were handed to a worker."""

        with self.lock:
            self._reap()
            self.purge()
            if not self.running:
                return []
            settings = self.settings()
            self._top_up(settings)
            return self._dispatch(settings)

    def _reap(self) -> None:
        for book_id, future in list(self.jobs.items()):
            if future.done():
                self.jobs.pop(book_id, None)

    def _top_up(self, settings: Settings) -> None:
        with Session(self.engine) as session:
            active = session.exec(
                select(func.count()).select_from(Book).where(col(Book.stage).not_in(FINISHED))
            ).one()
            room = settings.max_total - int(active)
            if room <= 0:
                return
            made = self._topic_counts(session)
            topics = list(session.exec(select(Topic).where(Topic.enabled).order_by(col(Topic.id))))
            created: list[Book] = []
            while room > 0:
                open_topics = [
                    topic
                    for topic in topics
                    if topic.count == 0 or made.get(topic.id or 0, 0) < topic.count
                ]
                if not open_topics:
                    break
                topic = min(open_topics, key=lambda item: (made.get(item.id or 0, 0), item.id))
                ever = session.exec(
                    select(func.count()).select_from(Book).where(Book.topic_id == topic.id)
                ).one()
                book = Book(
                    topic_id=topic.id,
                    genre=topic.genre,
                    idea=compose_idea(topic, int(ever) + 1),
                    chapters=topic.chapters,
                    stage=QUEUED,
                    created_at=self.clock(),
                    updated_at=self.clock(),
                )
                session.add(book)
                session.flush()
                book.slug = f"book-{book.id:04d}"
                session.add(book)
                session.flush()
                created.append(book)
                made[topic.id or 0] = made.get(topic.id or 0, 0) + 1
                room -= 1
            session.commit()
            ids = [book.id for book in created]
        for book_id in ids:
            self.log(book_id, "加入生产队列")

    def _dispatch(self, settings: Settings) -> list[int]:
        started: list[int] = []
        free = settings.concurrency - len(self.jobs)
        while free > 0:
            counts = self.counts()
            pick = self._next(settings, counts)
            if pick is None:
                break
            book, busy = pick
            assert book.id is not None
            self._move(book.id, [BUSY[busy]], busy, START_LABEL[busy])
            self.jobs[book.id] = self.executor.submit(self._work, book.id, busy)
            started.append(book.id)
            free -= 1
        return started

    def _next(self, settings: Settings, counts: dict[str, int]) -> tuple[Book, str] | None:
        def oldest(stage: str) -> Book | None:
            with Session(self.engine) as session:
                query = (
                    select(Book)
                    .where(Book.stage == stage)
                    .where(col(Book.id).not_in(list(self.jobs)))
                    .order_by(col(Book.updated_at), col(Book.id))
                )
                return session.exec(query).first()

        book = oldest(FULL_QUEUED)
        if book is not None:
            return book, FULL_WRITING
        if sum(counts[stage] for stage in TRIAL_BACKLOG) < settings.max_trial_backlog:
            book = oldest(TRIAL_QUEUED)
            if book is not None:
                return book, TRIAL_WRITING
        if sum(counts[stage] for stage in OUTLINE_BACKLOG) < settings.max_outline_backlog:
            book = oldest(QUEUED)
            if book is not None:
                return book, OUTLINING
        return None

    # work (runs in a pool thread)

    def _work(self, book_id: int, busy: str) -> None:
        try:
            book = self.book(book_id)
            settings = self.settings()
            if busy == OUTLINING:
                title = self.runner.outline(
                    self.root, book.slug, book.idea, book.genre, book.chapters, settings.dry_run
                )
                after = OUTLINE_REVIEW if settings.outline_review else TRIAL_QUEUED
                self._finish(book_id, busy, after, "大纲完成", title=title, written=0)
                return
            total = self.runner.card_count(self.root, book.slug)
            target = min(settings.trial_chapters, total) if busy == TRIAL_WRITING else total
            written = self.runner.locked_count(self.root, book.slug)
            while written < target:
                if not self._keep_going(book_id, busy):
                    self._finish(
                        book_id, busy, BUSY[busy], f"停在第 {written} 章，回到队列", written=written
                    )
                    return
                written = self.runner.write_upto(
                    self.root,
                    book.slug,
                    book.genre,
                    written + 1,
                    settings.drafts,
                    settings.dry_run,
                )
                self._progress(book_id, written)
            if busy == TRIAL_WRITING and written < total:
                after = TRIAL_REVIEW if settings.trial_review else FULL_QUEUED
                self._finish(book_id, busy, after, f"试读 {written} 章完成", written=written)
            else:
                self._finish(book_id, busy, DONE, f"全书 {written} 章完成", written=written)
        except Exception as exc:  # noqa: BLE001 - a failed book must not stop the factory
            self._finish(
                book_id,
                busy,
                FAILED,
                f"失败：{exc}",
                level="error",
                error=f"{type(exc).__name__}: {exc}",
                prev_stage=BUSY[busy],
            )
        finally:
            self.wake.set()

    def _keep_going(self, book_id: int, busy: str) -> bool:
        return self.running and self.book(book_id).stage == busy

    def _progress(self, book_id: int, written: int) -> None:
        with self.lock, Session(self.engine) as session:
            book = session.get(Book, book_id)
            if book is not None:
                book.written = written
                book.updated_at = self.clock()
                session.add(book)
                session.commit()

    def _finish(
        self,
        book_id: int,
        busy: str,
        stage: str,
        message: str,
        level: str = "info",
        **fields: Any,
    ) -> None:
        with self.lock, Session(self.engine) as session:
            book = session.get(Book, book_id)
            if book is None:
                return
            for key in ("title", "written"):
                if key in fields:
                    setattr(book, key, fields[key])
            if book.stage == busy:
                book.stage = stage
                for key, value in fields.items():
                    setattr(book, key, value)
            elif book.stage == TRASHED:
                message = f"{message}（已在回收站，不再继续）"
            book.updated_at = self.clock()
            session.add(book)
            session.commit()
        self.log(book_id, message, level)


START_LABEL = {OUTLINING: "开始写大纲", TRIAL_WRITING: "开始写试读", FULL_WRITING: "开始续写全书"}


def compose_idea(topic: Topic, number: int) -> str:
    """The idea a book is planned from: the topic core plus this book's own line."""

    lines = topic.idea_lines()
    parts = [topic.core.strip()]
    if lines:
        parts.append(lines[(number - 1) % len(lines)])
    elif topic.count != 1:
        parts.append(f"本批第 {number} 本：换一套人物、设定和开局，不要和同批其他书撞车。")
    return "\n\n".join(part for part in parts if part)
