"""Deterministic fake LLM. No network. Used by pytest and local dry-runs."""

from __future__ import annotations

import types
from collections.abc import Callable
from typing import Any, Literal, Union, get_args, get_origin

from pydantic import BaseModel

from novelforge.llm.client import T

Responder = Callable[[list[dict[str, str]], type[BaseModel]], BaseModel | None]


class FakeLLMClient:
    """Return scripted, canned, or synthesized Pydantic models. Call log is inspectable.

    Resolution order: `responder(messages, response_model)` if it returns a
    model, then `canned[response_model]`, then a synthesized empty instance.
    """

    def __init__(
        self,
        canned: dict[type[BaseModel], BaseModel] | None = None,
        defaults: dict[str, Any] | None = None,
        responder: Responder | None = None,
    ) -> None:
        self.canned = canned or {}
        self.defaults = defaults or {}
        self.responder = responder
        self.calls: list[dict[str, Any]] = []

    def complete(
        self,
        messages: list[dict[str, str]],
        response_model: type[T],
        *,
        role: str = "default",
        scene_id: str | None = None,
        **kwargs: Any,
    ) -> T:
        self.calls.append(
            {
                "messages": messages,
                "response_model": response_model.__name__,
                "role": role,
                "scene_id": scene_id,
                "kwargs": kwargs,
            }
        )
        if self.responder is not None:
            scripted = self.responder(messages, response_model)
            if scripted is not None:
                return scripted  # type: ignore[return-value]
        canned = self.canned.get(response_model)
        if canned is not None:
            return canned  # type: ignore[return-value]
        return synthesize_model(response_model, self.defaults)


def synthesize_model(model: type[T], defaults: dict[str, Any] | None = None) -> T:
    """Build a valid instance from field defaults plus a small type map."""

    payload: dict[str, Any] = dict(defaults or {})
    for name, field in model.model_fields.items():
        if name in payload:
            continue
        if not field.is_required():
            continue
        payload[name] = _placeholder(field.annotation)
    return model.model_validate(payload)


def _placeholder(annotation: Any) -> Any:
    origin = get_origin(annotation)
    if annotation is str:
        return ""
    if annotation is int:
        return 0
    if annotation is float:
        return 0.0
    if annotation is bool:
        return False
    if origin is list:
        return []
    if origin is dict:
        return {}
    if origin is Union or origin is types.UnionType:
        args = [arg for arg in get_args(annotation) if arg is not type(None)]
        return _placeholder(args[0]) if args else None
    if origin is Literal:
        return get_args(annotation)[0]
    if isinstance(annotation, type) and issubclass(annotation, BaseModel):
        return synthesize_model(annotation)
    return None
