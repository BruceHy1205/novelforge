"""Read a book's project files for the console: outline, chapters, manuscript.

The console is the author's desk, so it shows the full Canon. None of this is
fed back to the writer or the reader simulator.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from novelforge.store import load_book, load_canon, load_cards, manuscript_from_locked, project_dir


def outline(root: Path, slug: str) -> dict[str, Any]:
    directory = project_dir(slug, root)
    if not (directory / "canon.yaml").is_file():
        return {"canon": None, "cards": []}
    canon = load_canon(directory)
    cards = load_cards(directory)
    return {
        "canon": canon.model_dump(mode="json"),
        "cards": [card.model_dump(mode="json") for card in cards],
    }


def chapters(root: Path, slug: str) -> list[dict[str, Any]]:
    directory = project_dir(slug, root)
    book = load_book(directory)
    if book is None:
        return []
    titles = {card.scene_id: card.title for card in load_cards(directory)}
    return [
        {
            "scene_id": scene.scene_id,
            "title": titles.get(scene.scene_id, ""),
            "text": scene.text,
            "chars": len(scene.text),
        }
        for scene in book.locked_scenes
    ]


def manuscript(root: Path, slug: str, title: str) -> str:
    book = load_book(project_dir(slug, root))
    if book is None:
        return f"# {title}\n"
    return manuscript_from_locked(list(book.locked_scenes), book.canon.title or title)


def book_payload(root: Path, book: Any, events: list[Any]) -> dict[str, Any]:
    """Console book detail: row, canon, cards, locked chapters, and the event log."""

    return {
        **book.model_dump(),
        **outline(root, book.slug),
        "texts": chapters(root, book.slug),
        "events": [event.model_dump() for event in events],
    }


def artifacts(root: Path, slug: str) -> dict[str, Any]:
    """Paths under the factory root. Missing files are null, not invented."""

    directory = project_dir(slug, root)

    def rel(path: Path) -> str:
        return path.relative_to(root).as_posix()

    def maybe(path: Path) -> str | None:
        return rel(path) if path.is_file() else None

    cards_dir = directory / "scenes"
    card_paths = sorted(cards_dir.glob("sc-*.yaml")) if cards_dir.is_dir() else []
    return {
        "root": rel(directory) if directory.exists() else None,
        "canon": maybe(directory / "canon.yaml"),
        "cards": [rel(path) for path in card_paths],
        "manuscript": maybe(directory / "manuscript" / "book.md"),
        "models": maybe(directory / "models.yaml"),
        "idea": maybe(directory / "idea.txt"),
    }
