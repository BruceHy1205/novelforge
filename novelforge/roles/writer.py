"""Writer. The only input is a WriterView."""

from __future__ import annotations

from typing import Any

from novelforge.genres import Genre, fill, resolve
from novelforge.pacing.pace import craft_block
from novelforge.roles.prose import Prose
from novelforge.schema.scene import WriterView

SYSTEM_TEMPLATE = """你是<<identity>>。根据给你的场景视图，写这一章的完整正文。

先看 story：hook 是这本书的卖点，主角（protagonist_id）是读者代入的人，
他的 public_face、want、stake、edge 是你塑造他的材料。
story.background 是故事背景：时代、地方、开场前已经成立的局面。
把它当成已经发生的事来写，不要在开篇写成设定介绍。
story.concept 是核心设定。章节里的事要踩在这条规则上，不要中途改规则，也不要写成说明书。

这本书为什么而写（每一章都从这里出发）：
- story.core 是读者追这本书要的那种感觉。这一章要让读者真切感到 scene.reader_feeling，
  它是 core 在这一章的样子。写之前先想清楚：哪一段让读者心里一紧、一酸或一爽。
- story.approach.engine 是每章都要跑一圈的阅读动力；voice 是叙述声音，全书统一；
  principles 是写法原则；motifs 是反复出现的意象，这一章若出现，让它比上次多一层意思。
- story.themes 是这本书在追问的问题。scene.theme_beat 是这一章主角在主题上的那一步：
  把它写成一个具体的选择、一次代价、一句没说出口的话，让读者自己感到它。
  不写感悟，不写“他终于明白了”，不让人物讲道理。
- theme_notes 是前几章主题实际走到的地方。从那里接着走，可以推进、动摇或翻转，不要原地重复。

怎么写：
- 按 scene.beats 的起承转合写，每条展开成几段有画面、有对话、有内心的正文。
  先铺垫，再推进，中间要有转折，结尾前兑现 scene.payoff，写出 scene.state_change。
- 期待—压抑—释放：让读者看见 scene.reader_want，用 scene.obstacle 拖住，再给出 payoff。
- 让读者在乎主角：他的处境、他的习惯、他和别人的关系、他此刻想要什么、怕什么。
  可以写他的回忆、判断、恐惧和打算，可以写环境和氛围，只要它们服务情绪和悬念。
- 对话要有潜台词：人物说一半、绕开、撒小谎，读者从动作和停顿里看出来。
<<craft>>
- directives 是本章必须发生的事件，在合适的位置发生，不要逐条复述。
- 节奏有长有短：紧张处短句短段，铺垫和回忆处可以舒展。不要一句一段地堆砌。

开篇任务（scene.opening_task）：
<<opening>>

边界：
- 视角人物是读者的眼睛。不要写别人的内心，用他们的动作和话来表现。
- 只用视图里有的人物和设定，不要发明谜底、真实身份或秘密，不要替读者揭晓答案。
- 不要清点现场物品，不要写成动作清单。
- ending_hook 若有内容，本章最后一段要让读者看见它。
- answers_hook 若有内容，本章开头附近要碰到这件事。
- style_samples 只学语气，不要整句照抄。banned_patterns 里的说法不要用。
- earlier_summaries 和 prev_tail 是前文。承接它们，不要改写已经发生的事。
- 用中文，分段。不要写标题，不要写场景编号。"""


def system_prompt(genre: Genre | None = None) -> str:
    rules = resolve(genre)
    prompt = fill(SYSTEM_TEMPLATE, rules, "writer")
    if rules.beat_fields:
        lines = [f"- {name}：{text}" for name, text in rules.beat_fields.items()]
        prompt += (
            "\n\nscene.genre_beats 是本题材的专属节拍，都要在正文里发生，不要逐条复述：\n"
            + "\n".join(lines)
        )
    if rules.ledger_gain:
        prompt += (
            "\n\nledger_have 是前面各章已经拿到、这一章还能用的。"
            "ledger_spent 是已经用掉的，不能再写成还在手里。"
            "这一章新拿到的写进 genre_beats 的 "
            f"{rules.ledger_gain}，用掉的写进 {rules.ledger_spent or 'spent'}。"
        )
    return prompt


SYSTEM_PROMPT = system_prompt()


def draft_scene(view: WriterView, client: Any, *, genre: Genre | None = None) -> str:
    rules = resolve(genre)
    craft = craft_block(str(view.scene.pace), view.scene.length, rules.pace_craft)
    prose = client.complete(
        messages=[
            {"role": "system", "content": f"{system_prompt(rules)}\n\n{craft}"},
            {"role": "user", "content": view.model_dump_json()},
        ],
        response_model=Prose,
        role="writer",
        scene_id=view.scene.scene_id,
    )
    return prose.text.strip()


def write_baseline(idea: str, client: Any, *, scenes: int = 8, genre: Genre | None = None) -> str:
    """Control draft: one call, the idea only, no Canon and no gates."""

    kind = resolve(genre).prompt("baseline.kind")
    prose = client.complete(
        messages=[
            {
                "role": "system",
                "content": (
                    f"根据创意直接写一篇 {scenes} 场的中文{kind}。每场用一行“## 场次”隔开。"
                ),
            },
            {"role": "user", "content": idea.strip()},
        ],
        response_model=Prose,
        role="writer",
    )
    return prose.text.strip()
