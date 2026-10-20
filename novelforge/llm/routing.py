"""Per-role model routing, loaded from projects/<name>/models.yaml.

Defaults target the Volcengine Ark agent plan (OpenAI-compatible endpoint).
The API key is read from the environment variable named in
`provider.api_key_env` at call time; it is never written to YAML.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field

Role = Literal["architect", "planner", "writer", "reader_sim", "reviser", "gate", "critic"]
ROLES: tuple[Role, ...] = (
    "architect",
    "planner",
    "writer",
    "reader_sim",
    "reviser",
    "gate",
    "critic",
)
InstructorMode = Literal["json", "tools", "md_json"]

ARK_PLAN_BASE = "https://ark.cn-beijing.volces.com/api/plan/v3"
ARK_PLAN_KEY_ENV = "ark_plan_api_key"

THINKING_KIMI = "kimi-k3"
THINKING_KIMI_PREVIEW = "kimi-k2.8-preview"
THINKING_DEEPSEEK = "deepseek-v4-pro"
FLASH = "deepseek-v4.1-flash"

# The thinking model designs the story and judges drafts. Flash writes and screens.
DEFAULT_ROLES: dict[Role, str] = {
    "architect": THINKING_KIMI_PREVIEW,
    "planner": THINKING_KIMI_PREVIEW,
    "writer": FLASH,
    "reader_sim": FLASH,
    "reviser": FLASH,
    "gate": FLASH,
    "critic": THINKING_KIMI_PREVIEW,
}


class MissingAPIKeyError(RuntimeError):
    pass


class ProviderConfig(BaseModel):
    """`instructor_mode`: json works for every Ark plan model; kimi-k3 rejects tool calls."""

    model_config = ConfigDict(extra="forbid")

    api_base: str | None = ARK_PLAN_BASE
    api_key_env: str | None = ARK_PLAN_KEY_ENV
    instructor_mode: InstructorMode = "json"
    timeout: float = 180.0
    max_retries: int = 2
    max_tokens: int | None = None
    # Reasoning tokens count against max_tokens; long JSON can be cut off mid-object.
    disable_thinking: bool = False

    def api_key(self) -> str | None:
        if self.api_key_env is None:
            return None
        value = os.environ.get(self.api_key_env)
        if not value:
            raise MissingAPIKeyError(f"environment variable {self.api_key_env} is not set")
        return value


class ModelOverride(BaseModel):
    """Per-model provider settings. Unset fields fall back to `provider`."""

    model_config = ConfigDict(extra="forbid")

    timeout: float | None = None
    max_tokens: int | None = None
    disable_thinking: bool | None = None


def _default_overrides() -> dict[str, ModelOverride]:
    return {THINKING_KIMI_PREVIEW: ModelOverride(max_tokens=65536, disable_thinking=False)}


class ModelRouting(BaseModel):
    model_config = ConfigDict(extra="forbid")

    provider: ProviderConfig = Field(default_factory=ProviderConfig)
    default: str = FLASH
    roles: dict[Role, str] = Field(default_factory=lambda: dict(DEFAULT_ROLES))
    models: dict[str, ModelOverride] = Field(default_factory=_default_overrides)

    def model_for(self, role: str) -> str:
        return self.roles.get(role, self.default)  # type: ignore[call-overload]

    def settings_for(self, role: str) -> ProviderConfig:
        """Provider settings for the model behind `role`, with its override applied."""

        override = self.models.get(self.model_for(role))
        if override is None:
            return self.provider
        changes = {key: value for key, value in override.model_dump().items() if value is not None}
        return self.provider.model_copy(update=changes)

    def litellm_model(self, role: str) -> str:
        """Bare names on a custom OpenAI-compatible base get LiteLLM's `openai/` prefix."""

        model = self.model_for(role)
        if self.provider.api_base and "/" not in model:
            return f"openai/{model}"
        return model

    @classmethod
    def load(cls, path: Path) -> ModelRouting:
        if not path.is_file():
            return cls()
        data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        return cls.model_validate(data)

    def to_yaml(self) -> str:
        return yaml.safe_dump(self.model_dump(mode="json"), allow_unicode=True, sort_keys=False)


def default_routing_yaml() -> str:
    header = (
        "# Per-role model routing. kimi-k2.8-preview thinks: architect, planner, critic.\n"
        "# deepseek-v4.1-flash writes, revises, simulates readers, and screens.\n"
        "# `models` overrides provider settings per model. Other: kimi-k3, deepseek-v4-pro.\n"
        "# The key is read from provider.api_key_env.\n"
    )
    return header + ModelRouting().to_yaml()
