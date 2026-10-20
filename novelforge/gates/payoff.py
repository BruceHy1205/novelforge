"""Payoff gate: did this chapter's 爽点 land, or (on a build-up chapter) does the pressure pay?

The gate model sees the chapter text and writer-visible card fields only.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from novelforge.schema.gate import GateResult
from novelforge.schema.scene import SceneCard
from novelforge.schema.story import StoryBible
from novelforge.text import split_paragraphs

PAYOFF_PROMPT = """你是爽文网文的责编，只看这一章的爽点有没有落地。

本章计划：
{plan}

主角的底牌：{edge}

正文（段落编号）：
{text}

只写正文里读得到的东西：
- suppression：这一章谁在压主角、怎么压，读者有没有跟着憋住一口气。没有就留空。
- release：主角怎么出手、扳回了什么。没有就留空。
- reaction：对手和旁观者的反应，态度有没有翻过来。没有就留空。
- gain：主角实打实拿到的东西（实力、钱、地位、人、信息）。没有就留空。
- landed：一个追爽文的老读者读完会不会觉得爽；蓄力章（计划里没有打脸）就看他是不是更想看主角出手。
- problems：最伤爽感的问题，零到三条，每条一句话，写出段落编号。常见的有：
  爽点一句话带过、靠旁白宣布主角厉害、反派降智、主角圣母或受气太久不还手、
  金手指没有边界和代价、出手前没有压抑、出手后没有反应、收获说不清。"""

FIX = "把压抑写具体，让主角用自己的底牌当场出手，写出对手和旁观者的反应，落到主角拿到了什么"


class PayoffReport(BaseModel):
    model_config = ConfigDict(extra="forbid")

    suppression: str = ""
    release: str = ""
    reaction: str = ""
    gain: str = ""
    landed: bool = True
    problems: list[str] = Field(default_factory=list)


def payoff_plan(card: SceneCard) -> str:
    lines = [
        f"期待：{card.reader_want}",
        f"压抑：{card.obstacle}",
        f"释放：{card.payoff}",
        f"变化：{card.state_change}",
        f"读者感受：{card.reader_feeling}",
    ]
    for name, items in card.genre_beats.items():
        lines.extend(f"{name}：{item}" for item in items)
    return "\n".join(line for line in lines if not line.endswith("："))


def check_payoff(draft: str, card: SceneCard, story: StoryBible, client: Any) -> GateResult:
    hero = story.protagonist()
    text = "\n".join(
        f"[¶{index}] {paragraph}" for index, paragraph in enumerate(split_paragraphs(draft))
    )
    prompt = PAYOFF_PROMPT.format(
        plan=payoff_plan(card) or "（无）",
        edge=(hero.edge if hero else "") or "（未写）",
        text=text,
    )
    report = client.complete(
        messages=[{"role": "user", "content": prompt}],
        response_model=PayoffReport,
        role="gate",
        scene_id=card.scene_id,
    )
    details = {
        key: value
        for key, value in (
            ("suppression", report.suppression),
            ("release", report.release),
            ("reaction", report.reaction),
            ("gain", report.gain),
        )
        if value
    }
    if report.landed:
        return GateResult(gate_id="payoff", passed=True, reasons=["payoff landed"], details=details)
    reasons = ["payoff: 爽点没有落地", *report.problems[:3], f"payoff: {FIX}"]
    return GateResult(gate_id="payoff", passed=False, reasons=reasons, details=details)
