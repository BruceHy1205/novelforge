"""Creative intake: an external system hands in a finished brief.

`/api/topics` and `/api/books` stay the console's one-line batch path.
This router only validates, stores, and enqueues. It does not expand a
supplied Canon or outline into new creative material.
"""

from __future__ import annotations

from typing import Any, Literal

from fastapi import APIRouter, HTTPException, Request, Response
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from novelforge.factory import views
from novelforge.factory.intake import (
    Brief,
    RunRequest,
    create_book,
    enqueue,
    save_canon,
    save_models,
    save_outline,
)
from novelforge.factory.service import Factory, FactoryError
from novelforge.llm.routing import ModelRouting
from novelforge.schema.canon import Canon
from novelforge.schema.scene import SceneCard

router = APIRouter(prefix="/api/v1/creative", tags=["creative"])


class CreativeRun(BaseModel):
    """Enqueue onto the existing factory stages. Keep flags are additive."""

    model_config = ConfigDict(extra="forbid")

    stage: Literal["outline", "trial", "full"] = "outline"
    keep_canon: bool | None = None
    keep_outline: bool | None = None
    keep_cards: bool | None = None
    trial_chapters: int | None = Field(default=None, ge=1)
    stop_at: int | None = Field(default=None, ge=1)


class CreativeBookIn(BaseModel):
    """One book. `canon` is Canon, `cards` are SceneCards, `models` is ModelRouting."""

    model_config = ConfigDict(extra="forbid")

    external_id: str | None = None
    genre: str | None = None
    idea: str = ""
    core: str = ""
    chapters: int | None = Field(default=None, ge=1, le=500)
    canon: Canon | None = None
    cards: list[SceneCard] | None = None
    models: ModelRouting | None = None
    run: CreativeRun | None = None


class OutlineIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    cards: list[SceneCard] = Field(min_length=1)


def _factory(request: Request) -> Factory:
    return request.app.state.factory


def _guard(call: Any, *args: Any, **kwargs: Any) -> Any:
    try:
        return call(*args, **kwargs)
    except KeyError as exc:
        raise HTTPException(404, f"找不到 {exc}") from exc
    except (FactoryError, ValidationError) as exc:
        raise HTTPException(400, str(exc)) from exc


def _run(body: CreativeRun) -> RunRequest:
    return RunRequest(
        stage=body.stage,
        keep_canon=body.keep_canon,
        keep_outline=body.keep_outline,
        keep_cards=body.keep_cards,
        trial_chapters=body.trial_chapters,
        stop_at=body.stop_at,
    )


def present(factory: Factory, book_id: int) -> dict[str, Any]:
    book = factory.book(book_id)
    payload = views.book_payload(factory.root, book, factory.events(book_id, limit=200))
    payload["busy"] = book_id in factory.jobs
    payload["skip_architect"] = bool(book.keep_canon or book.keep_outline)
    payload["skip_planner"] = bool(book.keep_outline)
    payload["artifacts"] = views.artifacts(factory.root, book.slug)
    return payload


@router.post("/books")
def post_book(body: CreativeBookIn, request: Request, response: Response) -> dict[str, Any]:
    factory = _factory(request)
    brief = Brief(
        external_id=body.external_id,
        genre=body.genre,
        idea=body.idea,
        core=body.core,
        chapters=body.chapters,
        canon=body.canon,
        cards=body.cards,
        models=body.models,
        run=_run(body.run) if body.run is not None else None,
    )
    book, created = _guard(create_book, factory, brief)
    response.status_code = 201 if created else 200
    payload = _guard(present, factory, book.id)
    payload["created"] = created
    return payload


@router.put("/books/{book_id}/canon")
def put_canon(book_id: int, canon: Canon, request: Request) -> dict[str, Any]:
    factory = _factory(request)
    _guard(save_canon, factory, book_id, canon)
    return _guard(present, factory, book_id)


@router.put("/books/{book_id}/outline")
def put_outline(book_id: int, body: OutlineIn, request: Request) -> dict[str, Any]:
    factory = _factory(request)
    _guard(save_outline, factory, book_id, body.cards)
    return _guard(present, factory, book_id)


@router.put("/books/{book_id}/models")
def put_models(book_id: int, routing: ModelRouting, request: Request) -> dict[str, Any]:
    factory = _factory(request)
    _guard(save_models, factory, book_id, routing)
    return _guard(present, factory, book_id)


@router.post("/books/{book_id}/run")
def post_run(book_id: int, body: CreativeRun, request: Request) -> dict[str, Any]:
    factory = _factory(request)
    _guard(enqueue, factory, book_id, _run(body))
    return _guard(present, factory, book_id)


@router.get("/books/{book_id}")
def get_book(book_id: int, request: Request) -> dict[str, Any]:
    return _guard(present, _factory(request), book_id)
