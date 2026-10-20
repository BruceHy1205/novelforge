"""G11 retention. Would the reader tap the next chapter?

In the golden three chapters one reader walking away fails the scene. Later,
more than half have to walk away. Reasons carry only counts and the paragraph
index; the reviser gets the readers' own words through `retention_notes`,
after secret text is scrubbed.
"""

from __future__ import annotations

from novelforge.schema.gate import GateResult
from novelforge.schema.reader import ReaderReport

GOLDEN_SCENES = 3


def check_retention(reports: list[ReaderReport], *, opening: bool) -> GateResult:
    if not reports:
        return GateResult(gate_id="retention", passed=True, reasons=["no reader simulation"])
    quitting = [report for report in reports if not report.would_continue]
    limit = 0 if opening else len(reports) // 2
    passed = len(quitting) <= limit
    reasons = [f"{len(quitting)} of {len(reports)} readers would stop here"]
    boring = sorted(
        {report.boring_paragraph for report in quitting if report.boring_paragraph is not None}
    )
    if not passed and boring:
        reasons.append("readers lost interest at paragraph " + ", ".join(map(str, boring)))
    return GateResult(
        gate_id="retention",
        passed=passed,
        score=len(quitting) / len(reports),
        reasons=reasons,
        details={"quitting": str(len(quitting)), "opening": str(opening)},
    )


def retention_notes(reports: list[ReaderReport], secret_texts: list[str]) -> list[str]:
    """Why readers would stop, and what they want to see. Lines with secret text are dropped."""

    notes: list[str] = []
    for report in reports:
        for line in (
            "" if report.would_continue else f"读者不想追：{report.continue_reason}",
            f"读者最想看到：{report.craving}" if report.craving else "",
        ):
            if not line or line.endswith("：") or line in notes:
                continue
            if any(secret and secret in line for secret in secret_texts):
                continue
            notes.append(line)
    return notes
