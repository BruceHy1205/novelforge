"""Optional Langfuse tracing. Missing keys or any SDK error degrade to a no-op."""

from __future__ import annotations

import functools
import os
from collections.abc import Iterator
from contextlib import contextmanager, suppress
from typing import Any


def langfuse_enabled() -> bool:
    return bool(os.environ.get("LANGFUSE_SECRET_KEY") and os.environ.get("LANGFUSE_PUBLIC_KEY"))


@functools.cache
def _cached_client() -> Any | None:
    try:
        from langfuse import Langfuse

        return Langfuse()
    except Exception:
        return None


def get_langfuse_client() -> Any | None:
    if not langfuse_enabled():
        return None
    return _cached_client()


class Generation:
    """Handle for one LLM call. Every method is safe when tracing is off."""

    def __init__(self, observation: Any | None) -> None:
        self._observation = observation

    def finish(
        self,
        *,
        output: Any = None,
        usage: dict[str, int] | None = None,
        cost: float | None = None,
    ) -> None:
        self._safe_update(
            output=output,
            usage_details=usage,
            cost_details={"total": cost} if cost is not None else None,
        )

    def fail(self, exc: BaseException) -> None:
        self._safe_update(level="ERROR", status_message=f"{type(exc).__name__}: {exc}")

    def end(self) -> None:
        if self._observation is None:
            return
        with suppress(Exception):
            self._observation.end()

    def _safe_update(self, **fields: Any) -> None:
        if self._observation is None:
            return
        payload = {key: value for key, value in fields.items() if value is not None}
        with suppress(Exception):
            self._observation.update(**payload)


@contextmanager
def observe_generation(
    *,
    name: str,
    model: str,
    input: Any,
    metadata: dict[str, Any] | None = None,
) -> Iterator[Generation]:
    client = get_langfuse_client()
    observation = None
    if client is not None:
        try:
            observation = client.start_observation(
                name=name,
                as_type="generation",
                model=model,
                input=input,
                metadata=metadata,
            )
        except Exception:
            observation = None
    generation = Generation(observation)
    try:
        yield generation
    except BaseException as exc:
        generation.fail(exc)
        raise
    finally:
        generation.end()
