"""Factory tables: settings, topics, books, and an event log.

A book moves through stages. `*_queued` waits for a worker, `*ing` is being
worked on, `*_review` waits for a person (only when that review is on).
"""

from __future__ import annotations

from datetime import UTC, datetime

from sqlmodel import Field, SQLModel

QUEUED = "queued"
OUTLINING = "outlining"
OUTLINE_REVIEW = "outline_review"
TRIAL_QUEUED = "trial_queued"
TRIAL_WRITING = "trial_writing"
TRIAL_REVIEW = "trial_review"
FULL_QUEUED = "full_queued"
FULL_WRITING = "full_writing"
DONE = "done"
FAILED = "failed"
TRASHED = "trashed"

STAGES = (
    QUEUED,
    OUTLINING,
    OUTLINE_REVIEW,
    TRIAL_QUEUED,
    TRIAL_WRITING,
    TRIAL_REVIEW,
    FULL_QUEUED,
    FULL_WRITING,
    DONE,
    FAILED,
    TRASHED,
)

BUSY = {OUTLINING: QUEUED, TRIAL_WRITING: TRIAL_QUEUED, FULL_WRITING: FULL_QUEUED}
"""A busy stage and the queue it returns to when the work is interrupted."""

OUTLINE_BACKLOG = (OUTLINING, OUTLINE_REVIEW, TRIAL_QUEUED)
TRIAL_BACKLOG = (TRIAL_WRITING, TRIAL_REVIEW, FULL_QUEUED)
FINISHED = (DONE, TRASHED)


def now() -> datetime:
    return datetime.now(UTC)


class Settings(SQLModel, table=True):
    id: int = Field(default=1, primary_key=True)
    max_total: int = Field(default=50, ge=0)
    max_outline_backlog: int = Field(default=10, ge=1)
    max_trial_backlog: int = Field(default=10, ge=1)
    outline_review: bool = True
    trial_review: bool = True
    trial_chapters: int = Field(default=5, ge=1)
    concurrency: int = Field(default=1, ge=1, le=16)
    drafts: int = Field(default=1, ge=1, le=4)
    trash_days: int = Field(default=30, ge=1)
    dry_run: bool = False


class Topic(SQLModel, table=True):
    id: int | None = Field(default=None, primary_key=True)
    name: str
    genre: str = "mystery"
    core: str = ""
    ideas: str = ""
    count: int = Field(default=10, ge=0)
    chapters: int = Field(default=20, ge=1, le=500)
    enabled: bool = True
    created_at: datetime = Field(default_factory=now)

    def idea_lines(self) -> list[str]:
        return [line.strip() for line in self.ideas.splitlines() if line.strip()]


class Book(SQLModel, table=True):
    id: int | None = Field(default=None, primary_key=True)
    topic_id: int | None = Field(default=None, index=True)
    slug: str = Field(default="", index=True)
    genre: str = "mystery"
    idea: str = ""
    chapters: int = 20
    title: str = ""
    stage: str = Field(default=QUEUED, index=True)
    prev_stage: str = ""
    written: int = 0
    error: str = ""
    note: str = ""
    created_at: datetime = Field(default_factory=now)
    updated_at: datetime = Field(default_factory=now)
    trashed_at: datetime | None = None


class Event(SQLModel, table=True):
    id: int | None = Field(default=None, primary_key=True)
    book_id: int | None = Field(default=None, index=True)
    at: datetime = Field(default_factory=now)
    level: str = "info"
    message: str = ""
