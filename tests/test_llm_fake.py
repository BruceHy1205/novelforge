from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest

from novelforge import observability
from novelforge.llm.client import LiteLLMClient
from novelforge.llm.fake import FakeLLMClient
from novelforge.llm.routing import (
    ARK_PLAN_BASE,
    ARK_PLAN_KEY_ENV,
    DEFAULT_ROLES,
    MissingAPIKeyError,
    ModelRouting,
    ProviderConfig,
)
from novelforge.schema.reader import ReaderReport


@pytest.fixture
def ark_key(monkeypatch: pytest.MonkeyPatch) -> str:
    monkeypatch.setenv(ARK_PLAN_KEY_ENV, "test-key")
    return "test-key"


def test_fake_client_is_deterministic() -> None:
    client = FakeLLMClient(defaults={"persona_id": "p-reader"})
    first = client.complete([{"role": "user", "content": "hi"}], ReaderReport, role="reader_sim")
    second = client.complete([{"role": "user", "content": "hi"}], ReaderReport, role="reader_sim")
    assert first == second
    assert first.persona_id == "p-reader"
    assert [call["role"] for call in client.calls] == ["reader_sim", "reader_sim"]


def test_default_routing_targets_ark_plan() -> None:
    routing = ModelRouting()
    assert routing.provider.api_base == ARK_PLAN_BASE
    assert routing.provider.api_key_env == ARK_PLAN_KEY_ENV
    assert routing.provider.instructor_mode == "json"
    assert routing.roles == DEFAULT_ROLES
    assert routing.model_for("gate") == "deepseek-v4.1-flash"
    assert routing.litellm_model("writer") == "openai/deepseek-v4.1-flash"
    assert routing.model_for("critic") == "kimi-k2.8-preview"
    assert routing.model_for("planner") == "kimi-k2.8-preview"
    assert routing.model_for("reader_sim") == "deepseek-v4.1-flash"


def test_routing_picks_model_per_role() -> None:
    routing = ModelRouting(default="base-model", roles={"writer": "writer-model"})
    assert routing.model_for("writer") == "writer-model"
    assert routing.model_for("reader_sim") == "base-model"


def test_explicit_provider_prefix_is_kept() -> None:
    routing = ModelRouting(roles={"writer": "deepseek/deepseek-chat"})
    assert routing.litellm_model("writer") == "deepseek/deepseek-chat"


class _FakeObservation:
    def __init__(self, **kwargs: Any) -> None:
        self.start = kwargs
        self.updates: list[dict[str, Any]] = []
        self.ended = False

    def update(self, **kwargs: Any) -> None:
        self.updates.append(kwargs)

    def end(self) -> None:
        self.ended = True


class _FakeLangfuse:
    def __init__(self) -> None:
        self.observations: list[_FakeObservation] = []

    def start_observation(self, **kwargs: Any) -> _FakeObservation:
        observation = _FakeObservation(**kwargs)
        self.observations.append(observation)
        return observation


def _fake_create(**kwargs: Any) -> tuple[ReaderReport, Any]:
    raw = SimpleNamespace(
        usage=SimpleNamespace(prompt_tokens=10, completion_tokens=5, total_tokens=15)
    )
    return ReaderReport(persona_id="p-1"), raw


def test_litellm_client_routes_and_traces(monkeypatch: pytest.MonkeyPatch, ark_key: str) -> None:
    langfuse = _FakeLangfuse()
    monkeypatch.setattr(observability, "get_langfuse_client", lambda: langfuse)
    seen: dict[str, Any] = {}

    def create(**kwargs: Any) -> tuple[ReaderReport, Any]:
        seen.update(kwargs)
        return _fake_create(**kwargs)

    client = LiteLLMClient(ModelRouting(roles={"reader_sim": "sim-model"}), create_fn=create)
    report = client.complete(
        [{"role": "user", "content": "x"}], ReaderReport, role="reader_sim", scene_id="sc-03"
    )

    assert report.persona_id == "p-1"
    assert seen["model"] == "openai/sim-model"
    assert seen["api_base"] == ARK_PLAN_BASE
    assert seen["api_key"] == ark_key
    assert seen["mode"] == "json"
    observation = langfuse.observations[0]
    assert observation.start["as_type"] == "generation"
    assert observation.start["model"] == "sim-model"
    assert observation.start["metadata"] == {"role": "reader_sim", "scene_id": "sc-03"}
    assert observation.updates[0]["usage_details"]["total_tokens"] == 15
    assert observation.ended


def test_missing_api_key_fails_clearly() -> None:
    with pytest.raises(MissingAPIKeyError, match=ARK_PLAN_KEY_ENV):
        LiteLLMClient(create_fn=_fake_create).complete([], ReaderReport, role="gate")


def test_provider_without_base_or_key_passes_model_through() -> None:
    seen: dict[str, Any] = {}

    def create(**kwargs: Any) -> tuple[ReaderReport, Any]:
        seen.update(kwargs)
        return _fake_create(**kwargs)

    routing = ModelRouting(
        provider=ProviderConfig(api_base=None, api_key_env=None, instructor_mode="tools"),
        default="gpt-4o-mini",
        roles={},
    )
    LiteLLMClient(routing, create_fn=create).complete([], ReaderReport, role="gate")
    assert seen["model"] == "gpt-4o-mini"
    assert "api_base" not in seen and "api_key" not in seen
    assert seen["mode"] == "tools"
    assert "extra_body" not in seen


def test_disable_thinking_is_sent_to_the_provider() -> None:
    seen: dict[str, Any] = {}

    def create(**kwargs: Any) -> tuple[ReaderReport, Any]:
        seen.update(kwargs)
        return _fake_create(**kwargs)

    routing = ModelRouting(
        provider=ProviderConfig(api_base=None, api_key_env=None, disable_thinking=True)
    )
    LiteLLMClient(routing, create_fn=create).complete([], ReaderReport, role="gate")
    assert seen["extra_body"] == {"thinking": {"type": "disabled"}}


def test_a_thinking_model_keeps_reasoning_and_gets_more_tokens() -> None:
    seen: dict[str, Any] = {}

    def create(**kwargs: Any) -> tuple[ReaderReport, Any]:
        seen.clear()
        seen.update(kwargs)
        return _fake_create(**kwargs)

    routing = ModelRouting(
        provider=ProviderConfig(
            api_base=None, api_key_env=None, disable_thinking=True, max_tokens=16384
        )
    )
    client = LiteLLMClient(routing, create_fn=create)
    client.complete([], ReaderReport, role="critic")
    assert seen["model"] == "kimi-k2.8-preview"
    assert "extra_body" not in seen
    assert seen["max_tokens"] == 65536
    client.complete([], ReaderReport, role="writer")
    assert seen["extra_body"] == {"thinking": {"type": "disabled"}}
    assert seen["max_tokens"] == 16384


def test_litellm_client_records_errors(monkeypatch: pytest.MonkeyPatch, ark_key: str) -> None:
    langfuse = _FakeLangfuse()
    monkeypatch.setattr(observability, "get_langfuse_client", lambda: langfuse)

    def boom(**_kwargs: Any) -> tuple[ReaderReport, Any]:
        raise RuntimeError("provider down")

    with pytest.raises(RuntimeError):
        LiteLLMClient(create_fn=boom).complete([], ReaderReport, role="writer")
    observation = langfuse.observations[0]
    assert observation.updates[0]["level"] == "ERROR"
    assert observation.ended


def test_tracing_is_noop_without_keys(ark_key: str) -> None:
    assert observability.langfuse_enabled() is False
    report = LiteLLMClient(create_fn=_fake_create).complete([], ReaderReport, role="gate")
    assert report.persona_id == "p-1"


def test_a_call_that_outlives_its_deadline_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    import time

    from novelforge.llm import client as client_module
    from novelforge.llm.client import LLMDeadlineError

    monkeypatch.setattr(client_module, "DEADLINE_SLACK", 0.0)

    def slow(**kwargs: Any) -> tuple[ReaderReport, Any]:
        time.sleep(0.5)
        return _fake_create(**kwargs)

    routing = ModelRouting(
        provider=ProviderConfig(api_base=None, api_key_env=None, timeout=0.05, max_retries=0)
    )
    client = LiteLLMClient(routing, create_fn=slow)
    with pytest.raises(LLMDeadlineError):
        client.complete(
            [],
            ReaderReport,
            role="gate",
        )
