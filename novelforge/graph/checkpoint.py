"""Sqlite checkpoints. Schema types are allowlisted so resumes keep working."""

from __future__ import annotations

import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any

ALLOWED_MSGPACK_MODULES: list[tuple[str, str]] = [
    ("novelforge.schema.memory", "ChapterSummary"),
    ("novelforge.schema.memory", "GateStat"),
    ("novelforge.schema.memory", "ReviewMark"),
    ("novelforge.schema.canon", "Canon"),
    ("novelforge.schema.canon", "Secret"),
    ("novelforge.schema.canon", "RevealPlanItem"),
    ("novelforge.schema.clues", "Clue"),
    ("novelforge.schema.gate", "GateResult"),
    ("novelforge.schema.reader", "Persona"),
    ("novelforge.schema.reader", "PublicPOVState"),
    ("novelforge.schema.reader", "PublicReaderState"),
    ("novelforge.schema.reader", "ReaderGuess"),
    ("novelforge.schema.reader", "ReaderReport"),
    ("novelforge.schema.reader", "ReaderState"),
    ("novelforge.schema.reader", "SkipSpan"),
    ("novelforge.schema.scene", "LockedScene"),
    ("novelforge.schema.scene", "PublicSceneCard"),
    ("novelforge.schema.scene", "SceneCard"),
    ("novelforge.schema.scene", "WriterView"),
    ("novelforge.schema.state", "BookState"),
]


@contextmanager
def sqlite_checkpointer(path: str) -> Iterator[Any]:
    from langgraph.checkpoint.serde.jsonplus import JsonPlusSerializer
    from langgraph.checkpoint.sqlite import SqliteSaver

    serde = JsonPlusSerializer(allowed_msgpack_modules=ALLOWED_MSGPACK_MODULES)
    connection = sqlite3.connect(path, check_same_thread=False)
    try:
        yield SqliteSaver(connection, serde=serde)
    finally:
        connection.close()
