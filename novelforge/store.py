"""Project files: canon, scene cards, book state, snapshots, manuscript."""

from __future__ import annotations

from pathlib import Path

import yaml

from novelforge.schema.canon import Canon
from novelforge.schema.scene import LockedScene, SceneCard
from novelforge.schema.state import BookState


def project_dir(name: str, root: Path | None = None) -> Path:
    base = root if root is not None else Path.cwd()
    return base / "projects" / name


PROJECT_FILE = "project.yaml"


def load_genre_id(directory: Path) -> str | None:
    path = directory / PROJECT_FILE
    if not path.is_file():
        return None
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    value = data.get("genre")
    return str(value) if value else None


def save_genre_id(directory: Path, genre_id: str) -> None:
    path = directory / PROJECT_FILE
    data: dict[str, object] = {}
    if path.is_file():
        data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    data["genre"] = genre_id
    directory.mkdir(parents=True, exist_ok=True)
    path.write_text(yaml.safe_dump(data, allow_unicode=True, sort_keys=False), encoding="utf-8")


def save_model(path: Path, model: Canon | SceneCard | BookState) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        yaml.safe_dump(model.model_dump(mode="json"), allow_unicode=True, sort_keys=False),
        encoding="utf-8",
    )


def save_canon(directory: Path, canon: Canon) -> None:
    save_model(directory / "canon.yaml", canon)


def load_canon(directory: Path) -> Canon:
    data = yaml.safe_load((directory / "canon.yaml").read_text(encoding="utf-8")) or {}
    return Canon.model_validate(data)


def save_cards(directory: Path, cards: list[SceneCard]) -> None:
    scenes = directory / "scenes"
    scenes.mkdir(parents=True, exist_ok=True)
    for card in cards:
        save_model(scenes / f"{card.scene_id}.yaml", card)


def load_cards(directory: Path) -> list[SceneCard]:
    scenes = directory / "scenes"
    if not scenes.is_dir():
        return []
    cards = [
        SceneCard.model_validate(yaml.safe_load(path.read_text(encoding="utf-8")) or {})
        for path in sorted(scenes.glob("sc-*.yaml"))
    ]
    return cards


def save_book(directory: Path, book: BookState) -> None:
    save_model(directory / "state.yaml", book)


def load_book(directory: Path) -> BookState | None:
    path = directory / "state.yaml"
    if not path.is_file():
        return None
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    return BookState.model_validate(data)


def save_snapshot(directory: Path, scene_id: str, book: BookState) -> None:
    save_model(directory / "snapshots" / f"{scene_id}.yaml", book)


def load_snapshot(directory: Path, scene_id: str) -> BookState:
    path = directory / "snapshots" / f"{scene_id}.yaml"
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    return BookState.model_validate(data)


def write_manuscript(directory: Path, book: BookState, *, filename: str = "book.md") -> Path:
    parts = [f"# {book.canon.title}".rstrip()]
    for scene in book.locked_scenes:
        parts.append(f"## {scene.scene_id}\n\n{scene.text}")
    path = directory / "manuscript" / filename
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n\n".join(parts).rstrip() + "\n", encoding="utf-8")
    return path


def manuscript_from_locked(scenes: list[LockedScene], title: str) -> str:
    parts = [f"# {title}".rstrip()]
    for scene in scenes:
        parts.append(f"## {scene.scene_id}\n\n{scene.text}")
    return "\n\n".join(parts).rstrip() + "\n"
