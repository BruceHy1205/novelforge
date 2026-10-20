"""G9 drag. Fail when readers mark 15% or more of the scene to skip."""

from __future__ import annotations

from novelforge.schema.gate import GateResult
from novelforge.schema.reader import ReaderReport, SkipSpan
from novelforge.text import split_paragraphs

SKIP_LIMIT = 0.15


def skip_fraction(manuscript: str, spans: list[SkipSpan], scene_id: str) -> float:
    paragraphs = split_paragraphs(manuscript)
    if not paragraphs:
        return 0.0
    marked: set[int] = set()
    for span in spans:
        if scene_id and span.scene_id not in {scene_id, ""}:
            continue
        for index in span.paragraphs():
            if index < len(paragraphs):
                marked.add(index)
    return len(marked) / len(paragraphs)


def check_skim(
    manuscript: str,
    reports: list[ReaderReport] | None = None,
    *,
    scene_id: str = "",
    limit: float = SKIP_LIMIT,
) -> GateResult:
    if not reports:
        return GateResult(gate_id="skim", passed=True, reasons=["no reader simulation"])
    rates = [skip_fraction(manuscript, report.skip_spans, scene_id) for report in reports]
    average = sum(rates) / len(rates)
    passed = average < limit
    if passed:
        reason = f"skip rate {average:.2f}"
    else:
        reason = f"skip rate {average:.2f} exceeds {limit:.2f}"
    return GateResult(
        gate_id="skim",
        passed=passed,
        score=average,
        reasons=[reason],
        details={"limit": f"{limit:.2f}"},
    )
