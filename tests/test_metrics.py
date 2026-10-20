from __future__ import annotations

import pytest

from novelforge.eval.metrics import bin_confidence, jaccard, rank, spearman


def test_rank_averages_ties() -> None:
    assert rank([10, 20, 20, 30]) == [1.0, 2.5, 2.5, 4.0]


def test_spearman_perfect_and_inverse() -> None:
    assert spearman([1, 2, 3, 4], [10, 20, 30, 40]) == pytest.approx(1.0)
    assert spearman([1, 2, 3, 4], [4, 3, 2, 1]) == pytest.approx(-1.0)


def test_spearman_is_rank_based() -> None:
    assert spearman([1, 2, 3, 4], [1, 4, 9, 1000]) == pytest.approx(1.0)


def test_spearman_with_ties_matches_reference() -> None:
    # ranks x = [1.5, 1.5, 3, 4, 5], y = [1, 2.5, 2.5, 4.5, 4.5]
    # cov = 8.25, var_x = 9.5, var_y = 9  →  8.25 / sqrt(85.5)
    expected = 8.25 / (9.5 * 9) ** 0.5
    assert spearman([0, 0, 1, 2, 3], [0, 1, 1, 2, 2]) == pytest.approx(expected)


def test_spearman_undefined_cases() -> None:
    assert spearman([1], [1]) is None
    assert spearman([1, 1, 1], [1, 2, 3]) is None


def test_jaccard() -> None:
    assert jaccard({1, 2}, {2, 3}) == pytest.approx(1 / 3)
    assert jaccard(set(), set()) is None


def test_bin_confidence() -> None:
    assert bin_confidence("hint") == "hint"
    assert bin_confidence(0.05) == "none"
    assert bin_confidence(0.9) == "certain"
