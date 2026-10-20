"""Pace shape. Sprint and tight scenes cannot hide inside a long paragraph."""

from __future__ import annotations

from novelforge.gates.length import text_length
from novelforge.pacing.pace import normalize_pace
from novelforge.schema.gate import GateResult
from novelforge.text import split_paragraphs

MAX_PARAGRAPH: dict[str, int] = {
    "sprint": 36,
    "tight": 90,
    "slack": 220,
}


def check_pace(manuscript: str, pace: str) -> GateResult:
    normalized = normalize_pace(pace)
    paragraphs = split_paragraphs(manuscript)
    lengths = [text_length(paragraph) for paragraph in paragraphs]
    reasons: list[str] = []
    limit = MAX_PARAGRAPH.get(normalized)
    if limit is not None and any(count > limit for count in lengths):
        reasons.append(f"{normalized} paragraph is too long")
    if normalized == "slack" and text_length(manuscript) >= 80 and len(paragraphs) < 2:
        reasons.append("slack scene is a single block")
    passed = not reasons
    return GateResult(
        gate_id="pace",
        passed=passed,
        score=float(max(lengths) if lengths else 0),
        reasons=reasons or ["pace shape holds"],
        details={"pace": normalized},
    )
