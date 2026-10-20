"""HTTP API for the batch console, plus the built front end from `web/`."""

from __future__ import annotations

import os
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any, Literal

from fastapi import FastAPI, HTTPException
from fastapi.responses import HTMLResponse, PlainTextResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field, ValidationError

from novelforge.factory import views
from novelforge.factory.service import Factory, FactoryError
from novelforge.genres import DEFAULT_GENRE, genre_ids, get_genre

STATIC = Path(__file__).with_name("static")

MISSING_BUILD = """<!doctype html><meta charset="utf-8"><title>NovelForge</title>
<p>前端还没有构建。在仓库根目录运行：</p>
<pre>cd web &amp;&amp; npm install &amp;&amp; npm run build</pre>
<p>API 已经可用：<a href="/docs">/docs</a></p>"""


class Note(BaseModel):
    note: str = ""


class Batch(BaseModel):
    ids: list[int] = Field(default_factory=list)
    action: Literal["approve", "reject", "trash", "restore", "retry", "delete", "redo"]
    note: str = ""


def create_app(factory: Factory, *, serve: bool = True) -> FastAPI:
    @asynccontextmanager
    async def lifespan(_app: FastAPI):  # type: ignore[no-untyped-def]
        if serve:
            factory.serve()
        yield
        if serve:
            factory.close()

    app = FastAPI(title="NovelForge 批量生产台", lifespan=lifespan)
    app.state.factory = factory

    def guard(call: Any, *args: Any) -> Any:
        try:
            return call(*args)
        except KeyError as exc:
            raise HTTPException(404, f"找不到 {exc}") from exc
        except (FactoryError, ValidationError) as exc:
            raise HTTPException(400, str(exc)) from exc

    @app.get("/api/status")
    def status() -> dict[str, Any]:
        data = factory.status()
        from novelforge.llm.routing import ModelRouting

        env = ModelRouting().provider.api_key_env
        data["model_key"] = {"env": env, "set": bool(env and os.environ.get(env))}
        return data

    @app.post("/api/control/{action}")
    def control(action: Literal["start", "pause"]) -> dict[str, Any]:
        factory.start() if action == "start" else factory.pause()
        return {"running": factory.running}

    @app.get("/api/genres")
    def genres() -> list[dict[str, Any]]:
        return [
            {"id": genre_id, "name": get_genre(genre_id).name, "default": genre_id == DEFAULT_GENRE}
            for genre_id in genre_ids()
        ]

    @app.get("/api/settings")
    def get_settings() -> dict[str, Any]:
        return factory.settings().model_dump()

    @app.put("/api/settings")
    def put_settings(changes: dict[str, Any]) -> dict[str, Any]:
        return guard(factory.update_settings, changes).model_dump()

    @app.get("/api/topics")
    def topics() -> list[dict[str, Any]]:
        return factory.topics()

    @app.post("/api/topics")
    def create_topic(data: dict[str, Any]) -> dict[str, Any]:
        return guard(factory.save_topic, data).model_dump()

    @app.put("/api/topics/{topic_id}")
    def update_topic(topic_id: int, data: dict[str, Any]) -> dict[str, Any]:
        return guard(factory.save_topic, data, topic_id).model_dump()

    @app.delete("/api/topics/{topic_id}")
    def delete_topic(topic_id: int) -> dict[str, bool]:
        guard(factory.delete_topic, topic_id)
        return {"ok": True}

    @app.get("/api/books")
    def books(stage: str = "") -> list[dict[str, Any]]:
        stages = [item for item in stage.split(",") if item]
        busy = set(factory.jobs)
        return [{**book.model_dump(), "busy": book.id in busy} for book in factory.books(stages)]

    @app.get("/api/books/{book_id}")
    def book(book_id: int) -> dict[str, Any]:
        found = guard(factory.book, book_id)
        return {
            **found.model_dump(),
            **views.outline(factory.root, found.slug),
            "texts": views.chapters(factory.root, found.slug),
            "events": [event.model_dump() for event in factory.events(book_id, limit=200)],
        }

    @app.get("/api/books/{book_id}/manuscript", response_class=PlainTextResponse)
    def manuscript(book_id: int) -> PlainTextResponse:
        found = guard(factory.book, book_id)
        text = views.manuscript(factory.root, found.slug, found.title)
        name = f"{found.slug}.md"
        return PlainTextResponse(
            text,
            media_type="text/markdown; charset=utf-8",
            headers={"Content-Disposition": f'attachment; filename="{name}"'},
        )

    actions = {
        "approve": lambda book_id, note: factory.approve(book_id, note),
        "reject": lambda book_id, note: factory.trash(book_id, note),
        "trash": lambda book_id, note: factory.trash(book_id, note),
        "restore": lambda book_id, _note: factory.restore(book_id),
        "retry": lambda book_id, _note: factory.retry(book_id),
        "redo": lambda book_id, _note: factory.redo(book_id),
        "delete": lambda book_id, _note: factory.delete(book_id),
    }

    @app.post("/api/books/{book_id}/{action}")
    def act(book_id: int, action: str, body: Note | None = None) -> dict[str, Any]:
        if action not in actions:
            raise HTTPException(404, action)
        result = guard(actions[action], book_id, (body or Note()).note)
        return result.model_dump() if result is not None else {"ok": True}

    @app.post("/api/batch")
    def batch(body: Batch) -> dict[str, Any]:
        done: list[int] = []
        errors: dict[int, str] = {}
        for book_id in body.ids:
            try:
                actions[body.action](book_id, body.note)
                done.append(book_id)
            except (KeyError, FactoryError) as exc:
                errors[book_id] = str(exc)
        return {"done": done, "errors": errors}

    @app.post("/api/trash/empty")
    def empty_trash() -> dict[str, int]:
        return {"removed": factory.empty_trash()}

    @app.get("/api/events")
    def events(limit: int = 100) -> list[dict[str, Any]]:
        return [event.model_dump() for event in factory.events(limit=limit)]

    if (STATIC / "index.html").is_file():
        app.mount("/", StaticFiles(directory=STATIC, html=True), name="web")
    else:

        @app.get("/", response_class=HTMLResponse)
        def missing() -> str:
            return MISSING_BUILD

    return app
