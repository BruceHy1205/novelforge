"""G1 literal leak screen.

Exact substring, plus character-bigram containment for close paraphrases.
`embed_for_leak_screen` stays unwired: tests must not download bge-m3.
Reasons never quote the secret text.
"""

from __future__ import annotations

import re

from novelforge.schema.gate import GateResult

NEAR_MATCH_THRESHOLD = 0.8
MIN_NEAR_CHARS = 8
# A one-character secret matches ordinary prose. Exact match starts at 2.
MIN_EXACT_CHARS = 2


def embed_for_leak_screen(_texts: list[str]) -> list[list[float]]:
    """Reserved for bge-m3. Not wired; check_literal uses character bigrams."""

    raise NotImplementedError(
        "sentence-transformers/bge-m3 is not wired; check_literal uses character bigrams"
    )


def _compact(text: str) -> str:
    return re.sub(r"\s+", "", text)


def _bigrams(text: str) -> set[str]:
    compact = _compact(text)
    return {compact[index : index + 2] for index in range(len(compact) - 1)}


def secret_contained(manuscript: str, secret: str) -> float:
    """Share of the secret's character bigrams found in some nearby window."""

    secret_grams = _bigrams(secret)
    if len(_compact(secret)) < MIN_NEAR_CHARS or not secret_grams:
        return 0.0
    compact = _compact(manuscript)
    width = len(_compact(secret)) + 4
    best = 0.0
    step = max(1, width // 2)
    for index in range(0, max(1, len(compact) - 2), step):
        window = compact[index : index + width]
        if len(window) < 2:
            break
        overlap = len(secret_grams & _bigrams(window)) / len(secret_grams)
        best = max(best, overlap)
        if index + width >= len(compact):
            break
    return best


def check_literal(
    manuscript: str,
    secret_texts: list[str],
    *,
    near_threshold: float = NEAR_MATCH_THRESHOLD,
) -> GateResult:
    exact = [
        text
        for text in secret_texts
        if text and len(_compact(text)) >= MIN_EXACT_CHARS and text in manuscript
    ]
    near = [
        text
        for text in secret_texts
        if text and text not in exact and secret_contained(manuscript, text) >= near_threshold
    ]
    passed = not exact and not near
    reasons: list[str] = []
    if exact:
        reasons.append("exact-match leak")
    if near:
        reasons.append("near-match leak")
    if passed:
        reasons.append("no literal leak")
    return GateResult(
        gate_id="literal",
        passed=passed,
        score=0.0 if not passed else 1.0,
        reasons=reasons,
        details={"exact": str(len(exact)), "near": str(len(near))},
    )
