"""Send a completion to one routed role, whatever the caller asked for."""

from __future__ import annotations

from typing import Any


class RoleClient:
    """Force `role` on every call. Directive screening uses the small gate model."""

    def __init__(self, client: Any, role: str) -> None:
        self._client = client
        self._role = role

    def complete(
        self,
        messages: list[dict[str, str]],
        response_model: type[Any],
        **kwargs: Any,
    ) -> Any:
        kwargs["role"] = self._role
        return self._client.complete(messages, response_model, **kwargs)
