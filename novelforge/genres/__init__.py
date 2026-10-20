"""Genre rule sets. `get_genre(None)` is mystery, the original behaviour."""

from __future__ import annotations

from novelforge.genres.base import Genre, GenreError, fill

DEFAULT_GENRE = "mystery"

_GENRES: dict[str, Genre] = {}


def register_genre(genre: Genre) -> Genre:
    if genre.id in _GENRES and _GENRES[genre.id] is not genre:
        raise GenreError(f"genre {genre.id} is already registered")
    _GENRES[genre.id] = genre
    return genre


def _builtin() -> None:
    if DEFAULT_GENRE not in _GENRES:
        from novelforge.genres.mystery import MYSTERY
        from novelforge.genres.shuangwen import SHUANGWEN

        register_genre(MYSTERY)
        register_genre(SHUANGWEN)


def get_genre(genre_id: str | None = None) -> Genre:
    _builtin()
    key = genre_id or DEFAULT_GENRE
    try:
        return _GENRES[key]
    except KeyError as exc:
        known = ", ".join(sorted(_GENRES))
        raise GenreError(f"unknown genre {key}; known: {known}") from exc


def genre_ids() -> list[str]:
    _builtin()
    return sorted(_GENRES)


def resolve(genre: Genre | None) -> Genre:
    return genre if genre is not None else get_genre()


__all__ = ["DEFAULT_GENRE", "Genre", "GenreError", "fill", "genre_ids", "get_genre", "resolve"]
