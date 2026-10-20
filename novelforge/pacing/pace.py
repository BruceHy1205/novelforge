"""Pace changes the length budget and the way a scene is written."""

from __future__ import annotations

from novelforge.pacing.curve import KNOTS, correction_kind, tension_curve
from novelforge.schema.scene import PaceBin, SceneCard

PACE_ORDER: tuple[PaceBin, ...] = ("slack", "steady", "tight", "sprint")

# Chinese characters per chapter. One scene is one web-serial chapter.
# The writer and G3 both use this budget.
LENGTH_BUDGET: dict[PaceBin, int] = {
    "slack": 2800,
    "steady": 2600,
    "tight": 2400,
    "sprint": 2200,
}

# Distinct rhythm. A sprint prompt must not contain the slack permission, and
# the other way around. Tests lock that split.
PACE_CRAFT: dict[PaceBin, str] = {
    "slack": (
        "节奏是 slack。可以舒展：环境、回忆、日常和对话的潜台词都可以展开，"
        "但每一段都要让读者多知道一点、多担心一点。"
    ),
    "steady": (
        "节奏是 steady。叙述、对话和主角的内心交替推进，长段和短段搭配。铺垫要有，但不要停在原地。"
    ),
    "tight": (
        "节奏是 tight。场景推进快，句子偏短，少回忆。保留主角的感官和判断，紧张处可以一句一段。"
    ),
    "sprint": "节奏是 sprint。追逐、对峙或揭晓的节奏：短句短段，动作和对话为主，几乎不停顿。",
}

REVERSAL_DIRECTIVE = "立刻写出看得见的冲突，不要铺垫。"
REWARD_DIRECTIVE = "先给一个看得见的小结果，不要再加新的危机。"


def normalize_pace(pace: str) -> PaceBin:
    if pace in LENGTH_BUDGET:
        return pace  # type: ignore[return-value]
    return "steady"


def length_budget(pace: str, budget: dict[str, int] | None = None) -> int:
    table = budget if budget is not None else LENGTH_BUDGET
    return table[normalize_pace(pace)]


def craft_block(
    pace: str,
    length: int,
    craft: dict[str, str] | None = None,
) -> str:
    normalized = normalize_pace(pace)
    text = (craft if craft is not None else PACE_CRAFT)[normalized]
    return f"{text}\n篇幅预算是 {length} 个汉字，上下不要超过四分之一。"


def tighten(pace: str) -> PaceBin:
    normalized = normalize_pace(pace)
    index = PACE_ORDER.index(normalized)
    return PACE_ORDER[min(index + 1, len(PACE_ORDER) - 1)]


def loosen(pace: str) -> PaceBin:
    normalized = normalize_pace(pace)
    index = PACE_ORDER.index(normalized)
    return PACE_ORDER[max(index - 1, 0)]


def pace_for(target: float, previous: float | None) -> PaceBin:
    delta = 0.0 if previous is None else target - previous
    if target >= 0.8 or delta >= 0.2:
        return "sprint"
    if target >= 0.65 or delta >= 0.1:
        return "tight"
    if delta <= -0.15:
        return "slack"
    return "steady"


def apply_pacing(
    cards: list[SceneCard],
    *,
    knots: tuple[tuple[float, float], ...] = KNOTS,
    budget: dict[str, int] | None = None,
) -> list[SceneCard]:
    """Overwrite pace, length, and tension_target from the curve.

    The planner's prose beats stay. The numbers that drive the writer do not.
    """

    targets = tension_curve(len(cards), knots)
    paced: list[SceneCard] = []
    previous: float | None = None
    for card, target in zip(cards, targets, strict=True):
        pace = pace_for(target, previous)
        paced.append(
            card.model_copy(
                update={
                    "pace": pace,
                    "length": length_budget(pace, budget),
                    "tension_target": target,
                }
            )
        )
        previous = target
    return paced


def correct_upcoming(
    card: SceneCard,
    index: int,
    target: list[float],
    actual: list[float],
    budget: dict[str, int] | None = None,
) -> tuple[SceneCard, str]:
    """Force a reversal or a small reward from the last two scenes.

    The returned card is what the writer should see. Calling it twice does not
    stack the same directive.
    """

    kind = correction_kind(index, target, actual)
    if kind == "none":
        return card, kind
    if kind == "reversal":
        pace: PaceBin = "sprint"
        planned = target[index] if index < len(target) else card.tension_target
        tension = min(0.95, max(planned, card.tension_target) + 0.15)
        directive = REVERSAL_DIRECTIVE
    else:
        pace = "slack"
        planned = target[index] if index < len(target) else card.tension_target
        tension = max(0.3, min(planned, card.tension_target) - 0.2)
        directive = REWARD_DIRECTIVE
    directives = list(card.directives)
    if directive not in directives:
        directives.append(directive)
    updated = card.model_copy(
        update={
            "pace": pace,
            "length": length_budget(pace, budget),
            "tension_target": round(tension, 4),
            "directives": directives,
        }
    )
    return updated, kind
