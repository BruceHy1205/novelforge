"""Text helpers shared by the reader simulator and calibration."""

from __future__ import annotations


def split_paragraphs(text: str) -> list[str]:
    """One paragraph per non-empty line. Chinese prose usually uses single newlines."""

    return [line.strip() for line in text.splitlines() if line.strip()]
