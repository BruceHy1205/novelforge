"""G2 viewpoint. A blocked fact or another mind in the prose fails the scene.

Reasons do not quote the blocked fact.
"""

from __future__ import annotations

from novelforge.schema.canon import Secret
from novelforge.schema.gate import GateResult
from novelforge.schema.reader import POVState
from novelforge.text import split_paragraphs

INTERIOR_VERBS: tuple[str, ...] = ("想", "觉得", "知道", "记得", "暗道")


def pov_problem_indexes(
    manuscript: str,
    pov: POVState | None,
    secrets: list[Secret] | None = None,
    others: list[POVState] | None = None,
) -> list[int]:
    if pov is None:
        return []
    texts = {secret.id: secret.text for secret in secrets or []}
    blocked = [texts.get(secret_id, "") for secret_id in pov.blocked_secret_ids]
    blocked = [text for text in blocked if len(text) >= 2]
    names = [other.name.strip() for other in others or [] if other.character_id != pov.character_id]
    names = [name for name in names if len(name) >= 2]
    indexes: list[int] = []
    for index, paragraph in enumerate(split_paragraphs(manuscript)):
        if any(text in paragraph for text in blocked):
            indexes.append(index)
            continue
        if any(f"{name}{verb}" in paragraph for name in names for verb in INTERIOR_VERBS):
            indexes.append(index)
    return indexes


def check_pov(
    manuscript: str,
    pov: POVState | None = None,
    *,
    secrets: list[Secret] | None = None,
    others: list[POVState] | None = None,
) -> GateResult:
    if pov is None:
        return GateResult(gate_id="pov", passed=True, reasons=["no pov"])
    indexes = pov_problem_indexes(manuscript, pov, secrets, others)
    if not indexes:
        return GateResult(gate_id="pov", passed=True, reasons=["pov stays inside the viewpoint"])
    paragraphs = split_paragraphs(manuscript)
    blocked_hit = False
    texts = {secret.id: secret.text for secret in secrets or []}
    blocked = [texts.get(secret_id, "") for secret_id in pov.blocked_secret_ids]
    for index in indexes:
        if any(text and text in paragraphs[index] for text in blocked):
            blocked_hit = True
            break
    reason = "pov states a blocked fact" if blocked_hit else "pov enters another mind"
    return GateResult(gate_id="pov", passed=False, score=float(len(indexes)), reasons=[reason])
