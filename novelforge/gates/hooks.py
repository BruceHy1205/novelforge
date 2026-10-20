"""G10 empty hooks.

A declared ending has to show up in the prose. A declared answer to the
previous hook has to show up too. A reader question that vanishes, and is
not visible in this scene, was dropped.
Reasons do not quote the question.
"""

from __future__ import annotations

import re

from novelforge.schema.gate import GateResult

_MENTION_THRESHOLD = 0.6


def _compact(text: str) -> str:
    return re.sub(r"\s+", "", text)


def mentioned(needle: str, haystack: str) -> bool:
    compact_needle = _compact(needle)
    compact_hay = _compact(haystack)
    if len(compact_needle) < 2 or not compact_hay:
        return False
    if compact_needle in compact_hay:
        return True
    if len(compact_needle) < 4:
        return False
    grams = {compact_needle[index : index + 2] for index in range(len(compact_needle) - 1)}
    width = len(compact_needle) + 4
    step = max(1, width // 2)
    for index in range(0, max(1, len(compact_hay) - 1), step):
        window = compact_hay[index : index + width]
        if len(window) < 2:
            break
        window_grams = {window[pos : pos + 2] for pos in range(len(window) - 1)}
        if len(grams & window_grams) / len(grams) >= _MENTION_THRESHOLD:
            return True
        if index + width >= len(compact_hay):
            break
    return False


def check_hooks(
    draft: str,
    *,
    ending_hook: str = "",
    answers_hook: str = "",
    previous_questions: list[str] | None = None,
    wants_to_know: list[str] | None = None,
    is_last: bool = False,
) -> GateResult:
    reasons: list[str] = []
    if answers_hook and not mentioned(answers_hook, draft):
        reasons.append("previous hook is not answered")
    if ending_hook and not is_last and not mentioned(ending_hook, draft):
        reasons.append("ending hook is missing")
    asked = [question for question in (wants_to_know or []) if question]
    for question in previous_questions or []:
        if mentioned(question, draft):
            continue
        if any(mentioned(question, item) or mentioned(item, question) for item in asked):
            continue
        reasons.append("previous question was dropped without an answer")
        break
    passed = not reasons
    return GateResult(
        gate_id="hooks",
        passed=passed,
        score=0.0 if not passed else 1.0,
        reasons=reasons or ["hooks hold"],
    )
