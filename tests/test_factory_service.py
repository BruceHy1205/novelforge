"""Batch factory: limits, review stops, trash, purge. Dry-run client, no network."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from novelforge.factory import runner as real_runner
from novelforge.factory.models import (
    DONE,
    FAILED,
    FULL_QUEUED,
    OUTLINE_REVIEW,
    QUEUED,
    TRASHED,
    TRIAL_QUEUED,
    TRIAL_REVIEW,
)
from novelforge.factory.service import Factory, FactoryError, compose_idea
from novelforge.store import load_cards, project_dir


class Clock:
    def __init__(self) -> None:
        self.value = datetime(2026, 1, 1, tzinfo=UTC)

    def __call__(self) -> datetime:
        return self.value


def drain(factory: Factory, rounds: int = 60) -> None:
    for _ in range(rounds):
        started = factory.tick()
        for future in list(factory.jobs.values()):
            future.result()
        if not started:
            factory.tick()
            if not factory.jobs or all(job.done() for job in factory.jobs.values()):
                return


@pytest.fixture
def factory(tmp_path: Path):
    made = Factory(tmp_path / "factory", clock=Clock())
    made.update_settings({"dry_run": True})
    yield made
    made.close(wait=True)


def stages(factory: Factory) -> list[str]:
    return sorted(book.stage for book in factory.books())


def test_paused_factory_makes_nothing(factory: Factory) -> None:
    factory.save_topic({"name": "悬疑", "core": "渡口封了", "count": 3, "chapters": 3})
    assert factory.tick() == []
    assert factory.books() == []


def test_top_up_stops_at_max_total_and_topic_count(factory: Factory) -> None:
    factory.update_settings({"max_total": 4, "max_outline_backlog": 1})
    factory.save_topic({"name": "甲", "core": "甲", "count": 3, "chapters": 3})
    factory.save_topic({"name": "乙", "core": "乙", "count": 0, "chapters": 3})
    factory.start()
    factory.tick()
    books = factory.books()
    assert len(books) == 4
    by_topic = sorted(book.topic_id for book in books)
    assert by_topic == [1, 1, 2, 2]


def test_review_stops_and_backlogs_hold_production(factory: Factory) -> None:
    factory.update_settings(
        {"max_total": 5, "max_outline_backlog": 2, "max_trial_backlog": 1, "trial_chapters": 2}
    )
    factory.save_topic({"name": "悬疑", "core": "渡口封了", "count": 5, "chapters": 4})
    factory.start()
    drain(factory)
    assert stages(factory) == [OUTLINE_REVIEW, OUTLINE_REVIEW, QUEUED, QUEUED, QUEUED]
    outlined = factory.books([OUTLINE_REVIEW])[0]
    titles = [card.title for card in load_cards(project_dir(outlined.slug, factory.root))]
    assert titles == ["演练第1章", "演练第2章", "演练第3章", "演练第4章"]

    first, second = [book.id for book in factory.books([OUTLINE_REVIEW])]
    factory.approve(first)
    drain(factory)
    reviewed = factory.book(first)
    assert reviewed.stage == TRIAL_REVIEW
    assert reviewed.written == 2
    assert stages(factory).count(OUTLINE_REVIEW) == 2

    factory.approve(second)
    drain(factory)
    assert factory.book(second).stage == TRIAL_QUEUED

    factory.approve(first)
    drain(factory)
    assert factory.book(first).stage == DONE
    assert factory.book(first).written == 4
    assert factory.book(second).stage == TRIAL_REVIEW


def test_without_reviews_books_run_to_the_end(factory: Factory) -> None:
    factory.update_settings(
        {"max_total": 2, "outline_review": False, "trial_review": False, "concurrency": 2}
    )
    factory.save_topic(
        {"name": "爽文", "genre": "shuangwen", "core": "废灵根", "count": 2, "chapters": 3}
    )
    factory.start()
    drain(factory)
    assert stages(factory) == [DONE, DONE]
    assert all(book.written == 3 for book in factory.books())
    factory.tick()
    assert len(factory.books()) == 2


def test_reject_goes_to_trash_and_is_purged_after_the_retention(factory: Factory) -> None:
    clock: Clock = factory.clock  # type: ignore[assignment]
    factory.update_settings({"max_total": 1})
    factory.save_topic({"name": "悬疑", "core": "渡口封了", "count": 2, "chapters": 2})
    factory.start()
    drain(factory)
    book = factory.books([OUTLINE_REVIEW])[0]
    assert book.id is not None
    factory.trash(book.id)
    assert factory.book(book.id).stage == TRASHED
    factory.restore(book.id)
    assert factory.book(book.id).stage == OUTLINE_REVIEW
    factory.trash(book.id)

    factory.pause()
    clock.value += timedelta(days=29)
    factory.tick()
    assert factory.book(book.id).stage == TRASHED
    clock.value += timedelta(days=1)
    factory.tick()
    with pytest.raises(KeyError):
        factory.book(book.id)
    assert not project_dir(book.slug, factory.root).exists()


def test_rejected_book_is_replaced_from_the_topic(factory: Factory) -> None:
    factory.update_settings({"max_total": 1})
    factory.save_topic({"name": "悬疑", "core": "渡口封了", "count": 2, "chapters": 2})
    factory.start()
    drain(factory)
    first = factory.books([OUTLINE_REVIEW])[0]
    assert first.id is not None
    factory.trash(first.id)
    drain(factory)
    assert stages(factory) == [OUTLINE_REVIEW, TRASHED]


def test_redo_trial_rewrites_from_the_outline(factory: Factory) -> None:
    factory.update_settings({"max_total": 1, "outline_review": False, "trial_chapters": 1})
    factory.save_topic({"name": "悬疑", "core": "渡口封了", "count": 1, "chapters": 3})
    factory.start()
    drain(factory)
    book = factory.books([TRIAL_REVIEW])[0]
    assert book.id is not None and book.written == 1
    factory.redo(book.id)
    assert factory.book(book.id).stage == TRIAL_QUEUED
    assert real_runner.locked_count(factory.root, book.slug) == 0
    drain(factory)
    assert factory.book(book.id).stage == TRIAL_REVIEW
    with pytest.raises(FactoryError):
        factory.delete(book.id)


def test_failure_is_kept_and_can_be_retried(tmp_path: Path) -> None:
    class Broken:
        def __getattr__(self, name: str):  # type: ignore[no-untyped-def]
            return getattr(real_runner, name)

        @staticmethod
        def outline(*_args: object) -> str:
            raise RuntimeError("模型超时")

    factory = Factory(tmp_path / "f", runner=Broken())
    try:
        factory.update_settings({"dry_run": True, "max_total": 1})
        factory.save_topic({"name": "悬疑", "core": "渡口封了", "count": 1, "chapters": 2})
        factory.start()
        drain(factory)
        book = factory.books()[0]
        assert book.stage == FAILED and "模型超时" in book.error
        assert book.id is not None
        factory.runner = real_runner
        factory.retry(book.id)
        drain(factory)
        assert factory.book(book.id).stage == OUTLINE_REVIEW
    finally:
        factory.close(wait=True)


def test_interrupted_work_returns_to_its_queue(tmp_path: Path) -> None:
    root = tmp_path / "f"
    factory = Factory(root)
    factory.save_topic({"name": "悬疑", "core": "渡口", "count": 1})
    factory.running = True
    factory._top_up(factory.settings())
    book = factory.books()[0]
    assert book.id is not None
    factory._move(book.id, [QUEUED], "full_writing", "test")
    factory.close()
    again = Factory(root)
    assert again.book(book.id).stage == FULL_QUEUED
    again.close()


def test_settings_are_validated(factory: Factory) -> None:
    with pytest.raises(ValueError):
        factory.update_settings({"trial_chapters": 0})
    assert factory.settings().trial_chapters == 5


def test_compose_idea_cycles_the_idea_lines(factory: Factory) -> None:
    topic = factory.save_topic({"name": "甲", "core": "核心", "ideas": "一\n\n二\n", "count": 3})
    assert compose_idea(topic, 1) == "核心\n\n一"
    assert compose_idea(topic, 3) == "核心\n\n一"
    plain = factory.save_topic({"name": "乙", "core": "核心", "count": 3})
    assert compose_idea(plain, 2).startswith("核心\n\n本批第 2 本")
