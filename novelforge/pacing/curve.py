"""Target tension curve and the mid-book correction.

The curve is the plan. Reader reports are the actual. Two scenes in a row
below the plan force the next scene into a reversal; two scenes above it
buy a small visible reward.
"""

from __future__ import annotations

from novelforge.schema.reader import TensionBin

TENSION_LEVEL: dict[TensionBin, float] = {
    "flat": 0.15,
    "low": 0.35,
    "medium": 0.6,
    "high": 0.9,
}

# (position, tension). Web serials open hot: the first scene already has
# trouble in it. The late dip is one scene of breath before the reveal.
KNOTS: tuple[tuple[float, float], ...] = (
    (0.0, 0.66),
    (0.50, 0.76),
    (0.70, 0.86),
    (0.78, 0.45),
    (1.0, 0.95),
)

LOW_GAP = 0.2
HIGH_GAP = 0.15


def tension_curve(scene_count: int, knots: tuple[tuple[float, float], ...] = KNOTS) -> list[float]:
    if scene_count < 0:
        raise ValueError("scene_count must be >= 0")
    if scene_count == 0:
        return []
    if scene_count == 1:
        return [round(_at(0.55, knots), 4)]
    return [round(_at(index / (scene_count - 1), knots), 4) for index in range(scene_count)]


def _at(position: float, knots: tuple[tuple[float, float], ...] = KNOTS) -> float:
    position = min(1.0, max(0.0, position))
    for (left_x, left_y), (right_x, right_y) in zip(knots, knots[1:], strict=True):
        if position <= right_x:
            span = right_x - left_x
            mix = 0.0 if span == 0 else (position - left_x) / span
            return left_y + (right_y - left_y) * mix
    return knots[-1][1]


def tension_value(bin_name: str | None) -> float | None:
    if bin_name in TENSION_LEVEL:
        return TENSION_LEVEL[bin_name]  # type: ignore[index]
    return None


def mean_tension(bins: list[str | None]) -> float | None:
    scores = [score for score in (tension_value(name) for name in bins) if score is not None]
    if not scores:
        return None
    return sum(scores) / len(scores)


def curve_deviation(actual: list[float], target: list[float]) -> float:
    """Mean absolute gap. Empty overlap is 0."""

    count = min(len(actual), len(target))
    if count == 0:
        return 0.0
    return sum(abs(actual[index] - target[index]) for index in range(count)) / count


def correction_kind(index: int, target: list[float], actual: list[float]) -> str:
    """`reversal` after two low scenes, `reward` after two high scenes, else `none`."""

    if index < 2 or len(actual) < 2 or len(target) < 2:
        return "none"
    lows = 0
    highs = 0
    for offset in (1, 2):
        previous = index - offset
        if previous < 0 or previous >= len(actual) or previous >= len(target):
            return "none"
        gap = actual[previous] - target[previous]
        if gap <= -LOW_GAP:
            lows += 1
        if gap >= HIGH_GAP:
            highs += 1
    if lows == 2:
        return "reversal"
    if highs == 2:
        return "reward"
    return "none"
