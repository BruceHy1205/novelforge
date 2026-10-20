"""G4 banned phrasing and verbatim style-sample copies."""

from __future__ import annotations

from novelforge.schema.gate import GateResult
from novelforge.text import split_paragraphs

DEFAULT_BANNED: tuple[str, ...] = (
    "不禁",
    "宛如",
    "心中暗道",
    "一股暖流",
    "深吸一口气",
    "嘴角微微上扬",
    "目光深邃",
    "他不知道的是",
    "殊不知",
)

SAMPLE_COPY_CHARS = 12


def check_style(
    manuscript: str,
    banned: list[str] | None = None,
    samples: list[str] | None = None,
) -> GateResult:
    patterns = list(DEFAULT_BANNED if banned is None else banned)
    hits = [pattern for pattern in patterns if pattern and pattern in manuscript]
    copied = [
        sample
        for sample in samples or []
        if len(sample) >= SAMPLE_COPY_CHARS and sample in manuscript
    ]
    reasons: list[str] = []
    if hits:
        reasons.append("banned phrase: " + "、".join(hits))
    if copied:
        reasons.append("style sample copied verbatim")
    return GateResult(
        gate_id="style",
        passed=not reasons,
        score=float(len(hits) + len(copied)),
        reasons=reasons or ["style holds"],
    )


def style_problem_indexes(
    manuscript: str,
    reasons: list[str],
    samples: list[str] | None = None,
) -> list[int]:
    needles: list[str] = []
    for reason in reasons:
        if reason.startswith("banned phrase: "):
            phrase = reason.removeprefix("banned phrase: ")
            needles.extend(part for part in phrase.split("、") if part)
    if any(reason == "style sample copied verbatim" for reason in reasons):
        needles.extend(sample for sample in samples or [] if len(sample) >= SAMPLE_COPY_CHARS)
    if not needles:
        return []
    return [
        index
        for index, paragraph in enumerate(split_paragraphs(manuscript))
        if any(needle in paragraph for needle in needles)
    ]
