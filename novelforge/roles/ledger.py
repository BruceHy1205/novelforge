"""What the protagonist has, and what is already spent.

A genre names two beat fields. Locking a scene adds that card's lines to the
book. The writer of the next scene sees both lists and must not revive a
spent one.
"""

from __future__ import annotations

from novelforge.genres.base import Genre
from novelforge.schema.scene import SceneCard
from novelforge.schema.state import BookState


def _lines(card: SceneCard, name: str) -> list[str]:
    return [line.strip() for line in card.genre_beats.get(name, []) if line.strip()]


def _append(existing: list[str], lines: list[str]) -> list[str]:
    out = list(existing)
    for line in lines:
        if line not in out:
            out.append(line)
    return out


def fold_ledger(book: BookState, card: SceneCard, genre: Genre) -> BookState:
    """Record this card's gain and spent lines. Spent lines leave the held list."""

    if not genre.ledger_gain:
        return book
    have = _append(book.ledger_have, _lines(card, genre.ledger_gain))
    spent_now = _lines(card, genre.ledger_spent) if genre.ledger_spent else []
    spent = _append(book.ledger_spent, spent_now)
    have = [line for line in have if line not in spent]
    if have == list(book.ledger_have) and spent == list(book.ledger_spent):
        return book
    return book.model_copy(update={"ledger_have": have, "ledger_spent": spent})
