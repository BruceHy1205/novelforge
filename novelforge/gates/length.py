"""G3 length band. Chinese is counted in characters; spaced text in words."""

from __future__ import annotations

import re

from novelforge.schema.gate import GateResult


def text_length(text: str) -> int:
    characters = len(re.findall(r"[\u4e00-\u9fff]", text))
    words = len(text.split())
    return max(characters, words)


def check_length(manuscript: str, target_words: int, tolerance: float = 0.25) -> GateResult:
    count = text_length(manuscript)
    if target_words <= 0:
        return GateResult(gate_id="length", passed=True, reasons=["no target"])
    low = int(target_words * (1 - tolerance))
    high = int(target_words * (1 + tolerance))
    passed = low <= count <= high
    return GateResult(
        gate_id="length",
        passed=passed,
        score=count / target_words,
        reasons=[f"{count} units (target {target_words} ±{int(tolerance * 100)}%)"],
    )
