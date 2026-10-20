"""LiteLLM + Instructor wrapper with per-role routing and Langfuse tracing.

Tests must use FakeLLMClient or inject `create_fn`; the default path calls a
live provider.
"""

from __future__ import annotations

from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from concurrent.futures import TimeoutError as FutureTimeout
from typing import Any, Protocol, TypeVar

from pydantic import BaseModel

from novelforge.llm.routing import ModelRouting
from novelforge.observability import observe_generation

T = TypeVar("T", bound=BaseModel)

CreateFn = Callable[..., tuple[BaseModel, Any]]


class LLMClient(Protocol):
    def complete(
        self,
        messages: list[dict[str, str]],
        response_model: type[T],
        *,
        role: str = "default",
        scene_id: str | None = None,
        **kwargs: Any,
    ) -> T: ...


INSTRUCTOR_MODES = {"json": "JSON", "tools": "TOOLS", "md_json": "MD_JSON"}
DEADLINE_SLACK = 30.0


class LLMDeadlineError(TimeoutError):
    """A call outlived timeout × attempts. The worker thread is abandoned, not joined."""


def _within(deadline: float, fn: CreateFn, **kwargs: Any) -> tuple[BaseModel, Any]:
    # httpx's read timeout resets on every byte, so a slow trickle never trips it.
    pool = ThreadPoolExecutor(max_workers=1)
    future = pool.submit(fn, **kwargs)
    try:
        return future.result(timeout=deadline)
    except FutureTimeout as exc:
        raise LLMDeadlineError(f"model call exceeded {deadline:.0f}s") from exc
    finally:
        pool.shutdown(wait=False)


def _instructor_create(
    *,
    model: str,
    messages: list[dict[str, str]],
    response_model: type[BaseModel],
    mode: str = "json",
    **kwargs: Any,
) -> tuple[BaseModel, Any]:
    import instructor
    from litellm import completion

    client = instructor.from_litellm(
        completion, mode=getattr(instructor.Mode, INSTRUCTOR_MODES[mode])
    )
    return client.chat.completions.create_with_completion(
        model=model,
        messages=messages,
        response_model=response_model,
        **kwargs,
    )


class LiteLLMClient:
    """Instantiating opens no connection; `complete` does unless `create_fn` is injected."""

    def __init__(
        self,
        routing: ModelRouting | None = None,
        create_fn: CreateFn | None = None,
    ) -> None:
        self.routing = routing or ModelRouting()
        self._create = create_fn or _instructor_create

    def complete(
        self,
        messages: list[dict[str, str]],
        response_model: type[T],
        *,
        role: str = "default",
        scene_id: str | None = None,
        **kwargs: Any,
    ) -> T:
        provider = self.routing.settings_for(role)
        import httpx

        call_kwargs: dict[str, Any] = {
            "mode": provider.instructor_mode,
            "timeout": httpx.Timeout(provider.timeout, connect=30.0),
            "max_retries": provider.max_retries,
        }
        if provider.max_tokens:
            call_kwargs["max_tokens"] = provider.max_tokens
        if provider.disable_thinking:
            call_kwargs["extra_body"] = {"thinking": {"type": "disabled"}}
        if provider.api_base:
            call_kwargs["api_base"] = provider.api_base
        api_key = provider.api_key()
        if api_key:
            call_kwargs["api_key"] = api_key
        call_kwargs.update(kwargs)

        model = self.routing.model_for(role)
        deadline = provider.timeout * (provider.max_retries + 1) + DEADLINE_SLACK
        with observe_generation(
            name=role,
            model=model,
            input=messages,
            metadata={"role": role, "scene_id": scene_id},
        ) as generation:
            parsed, raw = _within(
                deadline,
                self._create,
                model=self.routing.litellm_model(role),
                messages=messages,
                response_model=response_model,
                **call_kwargs,
            )
            generation.finish(
                output=parsed.model_dump(mode="json"),
                usage=_usage(raw),
                cost=_cost(raw),
            )
        return parsed  # type: ignore[return-value]


def _usage(raw: Any) -> dict[str, int] | None:
    usage = getattr(raw, "usage", None)
    if usage is None:
        return None
    out = {
        key: value
        for key in ("prompt_tokens", "completion_tokens", "total_tokens")
        if isinstance(value := getattr(usage, key, None), int)
    }
    return out or None


def _cost(raw: Any) -> float | None:
    if raw is None or getattr(raw, "usage", None) is None:
        return None
    try:
        from litellm import completion_cost

        return float(completion_cost(completion_response=raw))
    except Exception:
        return None
