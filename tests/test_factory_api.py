"""Console API over the dry-run factory. The ASGI transport never opens a socket."""

from __future__ import annotations

from pathlib import Path

import httpx
import pytest
from fastapi.testclient import TestClient

from novelforge.factory.service import Factory
from novelforge.web.app import create_app

ASGI_SEND = httpx.Client.send


@pytest.fixture
def api(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(TestClient, "send", ASGI_SEND)
    factory = Factory(tmp_path / "factory")
    with TestClient(create_app(factory, serve=False)) as client:
        yield client, factory
    factory.close(wait=True)


def drain(factory: Factory) -> None:
    for _ in range(30):
        started = factory.tick()
        for future in list(factory.jobs.values()):
            future.result()
        if not started:
            return


def test_console_flow(api: tuple[TestClient, Factory]) -> None:
    client, factory = api
    status = client.get("/api/status").json()
    assert status["running"] is False
    assert status["settings"]["max_total"] == 50
    assert status["settings"]["trial_chapters"] == 5

    assert client.put("/api/settings", json={"trial_chapters": 0}).status_code == 400
    settings = client.put("/api/settings", json={"dry_run": True, "max_total": 2}).json()
    assert settings["max_total"] == 2

    genres = {item["id"] for item in client.get("/api/genres").json()}
    assert {"mystery", "shuangwen"} <= genres
    assert client.post("/api/topics", json={"name": "x", "genre": "nope"}).status_code == 400
    topic = client.post(
        "/api/topics", json={"name": "渡口", "core": "渡口封了", "count": 2, "chapters": 3}
    ).json()
    assert client.post("/api/control/start").json() == {"running": True}
    drain(factory)

    waiting = client.get("/api/books", params={"stage": "outline_review"}).json()
    assert len(waiting) == 2
    detail = client.get(f"/api/books/{waiting[0]['id']}").json()
    assert detail["canon"]["title"]
    assert len(detail["cards"]) == 3
    assert detail["events"]

    first, second = (book["id"] for book in waiting)
    result = client.post("/api/batch", json={"ids": [first, second], "action": "approve"}).json()
    assert sorted(result["done"]) == sorted([first, second])
    drain(factory)
    trial = client.get(f"/api/books/{first}").json()
    assert trial["stage"] == "done"
    assert len(trial["texts"]) == 3

    assert client.post(f"/api/books/{second}/reject", json={"note": "不好看"}).status_code == 200
    trash = client.get("/api/books", params={"stage": "trashed"}).json()
    assert [book["id"] for book in trash] == [second]
    assert trash[0]["note"] == "不好看"
    assert client.post(f"/api/books/{first}/delete").status_code == 400
    assert client.post("/api/trash/empty").json() == {"removed": 1}

    text = client.get(f"/api/books/{first}/manuscript").text
    assert text.startswith("# ")
    assert client.get("/api/topics").json()[0]["produced"] == 1
    assert client.delete(f"/api/topics/{topic['id']}").json() == {"ok": True}
    assert client.get("/api/books/999").status_code == 404
