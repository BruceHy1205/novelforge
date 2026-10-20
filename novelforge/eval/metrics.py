"""Small, dependency-free statistics for calibration."""

from __future__ import annotations

import math
from collections.abc import Sequence

from novelforge.schema.reader import CONFIDENCE_ORDER, Confidence, ConfidenceBin


def bin_confidence(value: Confidence) -> ConfidenceBin:
    """Coerce a 0–1 float or existing bin. Do not treat floats as calibrated."""

    if isinstance(value, str):
        return value
    if value < 0.15:
        return "none"
    if value < 0.4:
        return "hint"
    if value < 0.75:
        return "suspect"
    return "certain"


def confidence_index(value: ConfidenceBin) -> int:
    return CONFIDENCE_ORDER.index(value)


def rank(values: Sequence[float]) -> list[float]:
    """1-based ranks; ties share their average rank."""

    order = sorted(range(len(values)), key=lambda i: values[i])
    ranks = [0.0] * len(values)
    start = 0
    while start < len(order):
        end = start
        while end + 1 < len(order) and values[order[end + 1]] == values[order[start]]:
            end += 1
        average = (start + end) / 2 + 1
        for position in range(start, end + 1):
            ranks[order[position]] = average
        start = end + 1
    return ranks


def pearson(x: Sequence[float], y: Sequence[float]) -> float | None:
    if len(x) != len(y):
        raise ValueError("length mismatch")
    if len(x) < 2:
        return None
    mean_x = sum(x) / len(x)
    mean_y = sum(y) / len(y)
    cov = sum((a - mean_x) * (b - mean_y) for a, b in zip(x, y, strict=True))
    var_x = sum((a - mean_x) ** 2 for a in x)
    var_y = sum((b - mean_y) ** 2 for b in y)
    if var_x == 0 or var_y == 0:
        return None
    return cov / math.sqrt(var_x * var_y)


def spearman(x: Sequence[float], y: Sequence[float]) -> float | None:
    """Spearman rank correlation; None when undefined (n < 2 or a constant series)."""

    if len(x) != len(y):
        raise ValueError("length mismatch")
    if len(x) < 2:
        return None
    return pearson(rank(x), rank(y))


def jaccard(a: set[int], b: set[int]) -> float | None:
    union = a | b
    if not union:
        return None
    return len(a & b) / len(union)
