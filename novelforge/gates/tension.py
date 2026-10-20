"""G8 tension. Coarse bins from the reader simulator, compared with the scene target."""

from __future__ import annotations

from novelforge.pacing.curve import mean_tension
from novelforge.schema.gate import GateResult
from novelforge.schema.reader import ReaderReport

TENSION_SLACK = 0.2


def check_tension(
    reports: list[ReaderReport],
    target: float = 0.5,
) -> GateResult:
    average = mean_tension([report.tension for report in reports])
    if average is None:
        return GateResult(gate_id="tension", passed=True, reasons=["no tension report"])
    passed = average + 1e-9 >= target - TENSION_SLACK
    return GateResult(
        gate_id="tension",
        passed=passed,
        score=average,
        reasons=[f"tension {average:.2f} vs target {target:.2f}"],
    )
