"""Creative intake: validate, store, enqueue. No live model, no invented canon."""

from __future__ import annotations

from pathlib import Path

import httpx
import pytest
from fastapi.testclient import TestClient
from pydantic import BaseModel
from sqlalchemy import text
from sqlmodel import create_engine

from novelforge.factory.service import Factory
from novelforge.llm.fake import FakeLLMClient
from novelforge.pipeline import run_plan
from novelforge.roles.guess_judge import KeywordJudge
from novelforge.roles.prose import SceneDeck
from novelforge.schema.canon import Canon
from novelforge.schema.scene import SceneCard
from novelforge.store import load_canon, project_dir
from novelforge.web.app import create_app

ASGI_SEND = httpx.Client.send

SECRET = "注入的真相甲乙丙"


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


def canon_body(secret: str = SECRET) -> dict[str, object]:
    return {
        "title": "渡口夜话",
        "premise": "账房连夜离开",
        "story": {
            "hook": "渡口封了",
            "protagonist_id": "c1",
            "characters": [
                {"id": "c1", "name": "林舟", "role": "protagonist"},
                {"id": "c2", "name": "周先生", "role": "suspect"},
            ],
        },
        "secrets": [{"id": "S-1", "title": "账房", "text": secret, "probe_question": "谁最可疑？"}],
    }


def card_body(scene_id: str, title: str) -> dict[str, str]:
    return {"scene_id": scene_id, "title": title, "setting": "江边渡口"}


def test_create_from_idea_waits_until_run_then_replaces_the_directory(
    api: tuple[TestClient, Factory],
) -> None:
    client, factory = api
    factory.update_settings({"dry_run": True})
    created = client.post(
        "/api/v1/creative/books",
        json={"idea": "渡口封了", "core": "每一章近一步", "chapters": 2, "genre": "mystery"},
    )
    assert created.status_code == 201
    body = created.json()
    assert body["created"] is True
    assert body["mode"] == "plan_from_idea"
    assert body["enqueued"] is False
    assert body["stage"] == "queued"
    assert body["keep_canon"] is False
    assert "渡口封了" in body["idea"] and "每一章近一步" in body["idea"]
    rejected = client.post("/api/v1/creative/books", json={"genre": "nope", "idea": "x"})
    assert rejected.status_code == 400

    factory.start()
    assert factory.tick() == []
    assert factory.book(body["id"]).stage == "queued"
    assert not factory.jobs

    models = client.put(
        f"/api/v1/creative/books/{body['id']}/models",
        json={"provider": {"api_key_env": "CUSTOM_MODEL_KEY"}},
    )
    assert models.status_code == 200
    directory = project_dir(body["slug"], factory.root)
    marker = directory / "hand.txt"
    marker.write_text("wipe-me", encoding="utf-8")
    queued = client.post(f"/api/v1/creative/books/{body['id']}/run", json={"stage": "outline"})
    assert queued.status_code == 200
    assert queued.json()["enqueued"] is True
    assert queued.json()["stage"] == "queued"

    drain(factory)
    saved = factory.book(body["id"])
    assert saved.stage == "outline_review"
    assert saved.mode == "plan_from_idea"
    assert not marker.exists()
    assert load_canon(directory).title
    routing = (directory / "models.yaml").read_text(encoding="utf-8")
    assert "CUSTOM_MODEL_KEY" in routing
    assert "sk-" not in routing


def test_put_canon_skips_architect_and_survives_outline(api: tuple[TestClient, Factory]) -> None:
    client, factory = api
    factory.update_settings({"dry_run": True})
    created = client.post("/api/v1/creative/books", json={"idea": "渡口封了", "chapters": 2}).json()
    stored = client.put(f"/api/v1/creative/books/{created['id']}/canon", json=canon_body())
    assert stored.status_code == 200
    body = stored.json()
    assert body["mode"] == "keep_canon"
    assert body["skip_architect"] is True
    assert body["skip_planner"] is False
    assert body["canon"]["secrets"][0]["text"] == SECRET
    assert body["title"] == "渡口夜话"

    directory = project_dir(body["slug"], factory.root)
    canon_bytes = (directory / "canon.yaml").read_bytes()
    marker = directory / "hand.txt"
    marker.write_text("keep", encoding="utf-8")
    assert (
        client.post(
            f"/api/v1/creative/books/{body['id']}/run",
            json={"stage": "outline", "keep_canon": True, "trial_chapters": 1, "stop_at": 2},
        ).status_code
        == 200
    )
    factory.start()
    drain(factory)

    saved = client.get(f"/api/v1/creative/books/{body['id']}").json()
    assert saved["stage"] == "outline_review"
    assert saved["trial_chapters"] == 1
    assert saved["stop_at"] == 2
    assert (directory / "canon.yaml").read_bytes() == canon_bytes
    assert marker.read_text(encoding="utf-8") == "keep"
    assert SECRET in (directory / "canon.yaml").read_text(encoding="utf-8")
    assert "演练核心" not in (directory / "canon.yaml").read_text(encoding="utf-8")
    assert [card["title"] for card in saved["cards"]] == ["演练第1章", "演练第2章"]
    assert saved["artifacts"]["canon"].endswith("canon.yaml")
    assert saved["events"]


def test_injected_outline_skips_planner_and_survives_run(api: tuple[TestClient, Factory]) -> None:
    client, factory = api
    created = client.post(
        "/api/v1/creative/books",
        json={
            "external_id": "outline-1",
            "canon": canon_body(),
            "cards": [
                card_body("sc-01", "手写第一章"),
                card_body("sc-02", "手写第二章"),
            ],
        },
    )
    assert created.status_code == 201
    body = created.json()
    assert body["mode"] == "keep_outline"
    assert body["skip_architect"] is True
    assert body["skip_planner"] is True
    assert body["chapters"] == 2
    directory = project_dir(body["slug"], factory.root)
    assert "渡口封了" in (directory / "idea.txt").read_text(encoding="utf-8")
    canon_bytes = (directory / "canon.yaml").read_bytes()
    card_bytes = (directory / "scenes" / "sc-01.yaml").read_bytes()
    marker = directory / "hand.txt"
    marker.write_text("keep", encoding="utf-8")

    assert (
        client.post(
            f"/api/v1/creative/books/{body['id']}/run",
            json={"stage": "outline", "keep_outline": True, "keep_cards": True},
        ).status_code
        == 200
    )
    factory.start()
    drain(factory)
    assert factory.book(body["id"]).stage == "outline_review"
    assert (directory / "canon.yaml").read_bytes() == canon_bytes
    assert (directory / "scenes" / "sc-01.yaml").read_bytes() == card_bytes
    assert marker.read_text(encoding="utf-8") == "keep"
    assert load_canon(directory).secrets[0].text == SECRET

    factory.update_settings({"dry_run": True})
    ran = client.post(
        f"/api/v1/creative/books/{body['id']}/run",
        json={"stage": "trial", "keep_outline": True, "trial_chapters": 1, "stop_at": 1},
    )
    assert ran.status_code == 200
    assert ran.json()["stage"] == "trial_queued"
    drain(factory)
    after = client.get(f"/api/v1/creative/books/{body['id']}").json()
    assert after["stage"] == "trial_review"
    assert after["written"] == 1
    assert len(after["texts"]) == 1
    assert (directory / "canon.yaml").read_bytes() == canon_bytes
    assert (directory / "scenes" / "sc-01.yaml").read_bytes() == card_bytes
    assert (directory / "scenes" / "sc-02.yaml").is_file()
    assert marker.read_text(encoding="utf-8") == "keep"
    assert after["artifacts"]["manuscript"].endswith("book.md")


def test_run_requires_cards_before_trial_and_stores_keep_flags(
    api: tuple[TestClient, Factory],
) -> None:
    client, _factory = api
    created = client.post("/api/v1/creative/books", json={"idea": "只有一句"}).json()
    missing = client.post(
        f"/api/v1/creative/books/{created['id']}/run",
        json={"stage": "trial", "keep_canon": True},
    )
    assert missing.status_code == 400
    client.put(f"/api/v1/creative/books/{created['id']}/canon", json=canon_body())
    still = client.post(
        f"/api/v1/creative/books/{created['id']}/run",
        json={"stage": "full", "keep_cards": True},
    )
    assert still.status_code == 400
    client.put(
        f"/api/v1/creative/books/{created['id']}/outline",
        json={"cards": [card_body("sc-01", "手写第一章"), card_body("sc-02", "旧章")]},
    )
    replaced = client.put(
        f"/api/v1/creative/books/{created['id']}/outline",
        json={"cards": [card_body("sc-01", "只剩一章")]},
    )
    assert replaced.status_code == 200
    assert replaced.json()["skip_planner"] is True
    assert [card["scene_id"] for card in replaced.json()["cards"]] == ["sc-01"]
    directory = project_dir(created["slug"], _factory.root)
    assert not (directory / "scenes" / "sc-02.yaml").exists()
    queued = client.post(
        f"/api/v1/creative/books/{created['id']}/run",
        json={"stage": "full", "keep_outline": True, "stop_at": 1},
    )
    assert queued.status_code == 200
    assert queued.json()["stage"] == "full_queued"
    assert queued.json()["keep_outline"] is True
    assert queued.json()["stop_at"] == 1


def test_external_id_is_idempotent(api: tuple[TestClient, Factory]) -> None:
    client, factory = api
    first = client.post(
        "/api/v1/creative/books",
        json={"external_id": "desk-7", "idea": "第一句"},
    )
    assert first.status_code == 201
    second = client.post(
        "/api/v1/creative/books",
        json={"external_id": "desk-7", "idea": "第一句"},
    )
    assert second.status_code == 200
    assert second.json()["created"] is False
    assert second.json()["id"] == first.json()["id"]
    third = client.post(
        "/api/v1/creative/books",
        json={"external_id": " desk-7 ", "canon": canon_body()},
    )
    assert third.status_code == 200
    assert third.json()["id"] == first.json()["id"]
    assert third.json()["keep_canon"] is True
    assert third.json()["canon"]["title"] == "渡口夜话"
    assert len(factory.books()) == 1
    assert client.get("/api/v1/creative/books/999").status_code == 404
    thin = canon_body()
    story = thin["story"]
    assert isinstance(story, dict)
    story["characters"] = [story["characters"][0]]
    rejected = client.put(f"/api/v1/creative/books/{first.json()['id']}/canon", json=thin)
    assert rejected.status_code == 400


def test_models_reject_raw_keys(api: tuple[TestClient, Factory]) -> None:
    client, factory = api
    created = client.post("/api/v1/creative/books", json={"idea": "渡口"}).json()
    raw = client.put(
        f"/api/v1/creative/books/{created['id']}/models",
        json={"provider": {"api_key": "sk-live-secret"}},
    )
    assert raw.status_code == 422
    named = client.put(
        f"/api/v1/creative/books/{created['id']}/models",
        json={"provider": {"api_key_env": "sk-live-secret"}},
    )
    assert named.status_code == 400
    ok = client.put(
        f"/api/v1/creative/books/{created['id']}/models",
        json={
            "provider": {"api_key_env": "ark_plan_api_key"},
            "roles": {"writer": "deepseek-v4.1-flash"},
        },
    )
    assert ok.status_code == 200
    text = (project_dir(created["slug"], factory.root) / "models.yaml").read_text(encoding="utf-8")
    assert "ark_plan_api_key" in text
    assert "sk-" not in text
    bad_card = client.put(
        f"/api/v1/creative/books/{created['id']}/outline",
        json={"cards": [{"scene_id": "sc-1", "title": "错"}]},
    )
    assert bad_card.status_code == 400


def test_topic_outline_still_replaces_the_project(tmp_path: Path) -> None:
    factory = Factory(tmp_path / "factory")
    try:
        factory.update_settings({"dry_run": True, "max_total": 1})
        factory.save_topic({"name": "悬疑", "core": "渡口封了", "count": 1, "chapters": 2})
        factory.start()
        factory._top_up(factory.settings())
        book = factory.books()[0]
        assert book.id is not None and book.enqueued is True and book.keep_canon is False
        directory = project_dir(book.slug, factory.root)
        directory.mkdir(parents=True)
        (directory / "hand.txt").write_text("wipe", encoding="utf-8")
        (directory / "canon.yaml").write_text("title: 手写\n", encoding="utf-8")
        drain(factory)
        assert factory.book(book.id).stage == "outline_review"
        assert not (directory / "hand.txt").exists()
        assert load_canon(directory).title != "手写"
    finally:
        factory.close(wait=True)


def test_upgrade_adds_creative_columns(tmp_path: Path) -> None:
    root = tmp_path / "factory"
    root.mkdir()
    engine = create_engine(f"sqlite:///{root / 'factory.sqlite'}")
    with engine.begin() as conn:
        conn.execute(
            text(
                """
                CREATE TABLE book (
                    id INTEGER PRIMARY KEY,
                    topic_id INTEGER,
                    slug VARCHAR NOT NULL,
                    genre VARCHAR NOT NULL,
                    idea VARCHAR NOT NULL,
                    chapters INTEGER NOT NULL,
                    title VARCHAR NOT NULL,
                    stage VARCHAR NOT NULL,
                    prev_stage VARCHAR NOT NULL,
                    written INTEGER NOT NULL,
                    error VARCHAR NOT NULL,
                    note VARCHAR NOT NULL,
                    created_at DATETIME NOT NULL,
                    updated_at DATETIME NOT NULL,
                    trashed_at DATETIME
                )
                """
            )
        )
        conn.execute(
            text(
                """
                INSERT INTO book (
                    slug, genre, idea, chapters, title, stage, prev_stage, written, error, note,
                    created_at, updated_at
                ) VALUES (
                    'book-0007', 'mystery', '雨', 2, '', 'queued', '', 0, '', '',
                    '2026-01-01 00:00:00', '2026-01-01 00:00:00'
                )
                """
            )
        )
    engine.dispose()
    factory = Factory(root)
    try:
        book = factory.books()[0]
        assert book.slug == "book-0007"
        assert book.mode == "plan_from_idea"
        assert book.enqueued is True
        assert book.keep_canon is False
        assert book.keep_outline is False
        assert book.external_id is None
    finally:
        factory.close(wait=True)


def test_freeze_canon_does_not_call_the_architect(tmp_path: Path) -> None:
    directory = tmp_path / "projects" / "demo"
    directory.mkdir(parents=True)
    source = Canon.model_validate(canon_body())
    from novelforge.store import save_canon

    save_canon(directory, source)

    def respond(_messages: list[dict[str, str]], model: type[BaseModel]) -> BaseModel | None:
        if model is SceneDeck:
            return SceneDeck(scenes=[SceneCard(scene_id="sc-01", title="规划")])
        return None

    client = FakeLLMClient(responder=respond)
    run_plan(
        "demo",
        "渡口封了",
        client,
        KeywordJudge({}),
        root=tmp_path,
        scenes=1,
        personas=[],
        keep_canon=True,
        freeze_canon=True,
    )
    assert not any(call["role"] == "architect" for call in client.calls)
    assert any(call["role"] == "planner" for call in client.calls)
    assert load_canon(directory).secrets[0].text == SECRET
    assert load_canon(directory).story.core == ""
