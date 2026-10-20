"""Block outbound HTTP so pytest stays offline."""

from __future__ import annotations

import os

import pytest

# litellm fetches its model cost map over HTTP at import time unless told not to.
os.environ.setdefault("LITELLM_LOCAL_MODEL_COST_MAP", "True")
for _key in ("LANGFUSE_SECRET_KEY", "LANGFUSE_PUBLIC_KEY", "ark_plan_api_key"):
    os.environ.pop(_key, None)


@pytest.fixture(autouse=True)
def no_network(monkeypatch: pytest.MonkeyPatch) -> None:
    def boom(*_args: object, **_kwargs: object) -> None:
        raise RuntimeError("network disabled in unit tests")

    try:
        import httpx

        monkeypatch.setattr(httpx.Client, "send", boom)
        monkeypatch.setattr(httpx.AsyncClient, "send", boom)
    except ImportError:
        pass

    try:
        import requests

        monkeypatch.setattr(requests.sessions.Session, "request", boom)
    except ImportError:
        pass
