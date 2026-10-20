"""Critic: a web-serial reader picks the chapter they would rather keep reading.

Same constitution as the reader simulator: the critic sees locked manuscript
text, candidate drafts, and a plain-text brief built from the public story
layer. Never Canon, SceneCard, BookState, or WriterView. Absolute "would you
continue" questions let flat prose pass; a side-by-side choice does not.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from novelforge.genres import Genre, fill, resolve
from novelforge.schema.scene import LockedScene, PublicSceneCard
from novelforge.schema.story import StoryBible

CONTEXT_CHARS = 1500

SYSTEM_TEMPLATE = """你是<<identity>>。
下面是这本书的写作纲领、前文的结尾，以及同一章的几份候选稿。
选出你最想读完、读完最想点下一章的那一份。

判断标准：
- 有没有让你真切感到纲领里的核心体验和本章该有的感受，而不是只知道发生了什么。
- 本章的主题落点有没有落成主角一个具体的选择或代价；有没有说教、写感悟、让人物讲道理。
- 叙述声音是否符合纲领，叙事引擎这一章有没有跑起来。
- 有没有让你在乎主角：他的处境、关系、欲望和恐惧。
<<setup>>
<<craft>>
- 节奏是否有起伏，结尾钩子是否让你想马上看下一章。
- 是不是像动作清单、一句一段地堆砌，或者把答案直接说破。
- 和人物设定、前文有没有矛盾（例如失聪的人“听见”声音、地点和时间对不上）。

choice 填候选稿编号（从 0 开始）。reason 用一句话说为什么。
notes 给被选中的那份写一到三条具体的修改意见，指出哪一段、改成什么样；有矛盾必须写进来。没有就留空。
theme_hit：被选中的那份有没有让主题落点和核心体验真正落地。
theme_note：被选中的那份读完之后，主题实际走到了哪里——主角做了什么选择、付出了什么、
对主题追问的回答变成了什么、留下了什么新问题。一两句，只写正文里读得到的东西。"""


class CriticVerdict(BaseModel):
    model_config = ConfigDict(extra="forbid")

    choice: int = 0
    reason: str = ""
    notes: list[str] = Field(default_factory=list)
    theme_hit: bool = True
    theme_note: str = ""


def render_brief(story: StoryBible, scene: PublicSceneCard) -> str:
    """Plain-text writing brief from writer-visible fields only."""

    lines = [
        f"故事背景：{story.background}",
        f"核心设定：{story.concept}",
        f"核心体验：{story.core}",
    ]
    for theme in story.themes:
        lines.append(f"主题 {theme.id}：{theme.question}（{theme.tension}）")
    approach = story.approach
    lines.append(f"叙事引擎：{approach.engine}")
    lines.append(f"叙述声音：{approach.voice}")
    if approach.motifs:
        lines.append("反复意象：" + "；".join(approach.motifs))
    if approach.principles:
        lines.append("写法原则：" + "；".join(approach.principles))
    hero = story.protagonist()
    if hero is not None:
        lines.append(f"主角：{hero.name}，{hero.public_face}；优势：{hero.edge}")
    lines.append(f"本章主题落点：{scene.theme_beat}")
    lines.append(f"本章读者感受：{scene.reader_feeling}")
    return "\n".join(line for line in lines if not line.endswith("：") and "：（）" not in line)


def system_prompt(genre: Genre | None = None) -> str:
    return fill(SYSTEM_TEMPLATE, resolve(genre), "critic")


SYSTEM_PROMPT = system_prompt()


def build_messages(
    manuscript: list[LockedScene],
    drafts: list[str],
    brief: str = "",
    genre: Genre | None = None,
) -> list[dict[str, str]]:
    context = manuscript[-1].text[-CONTEXT_CHARS:] if manuscript else "（这是第一章）"
    blocks = "\n\n".join(f"## 候选稿 {index}\n{text}" for index, text in enumerate(drafts))
    head = f"# 写作纲领\n{brief}\n\n" if brief else ""
    return [
        {"role": "system", "content": system_prompt(genre)},
        {"role": "user", "content": f"{head}# 前文结尾\n{context}\n\n{blocks}"},
    ]


def choose_draft(
    manuscript: list[LockedScene],
    drafts: list[str],
    client: Any,
    brief: str = "",
    *,
    genre: Genre | None = None,
) -> CriticVerdict:
    """Pick one of `drafts`. A single draft is still read when a brief asks for theme notes."""

    if len(drafts) <= 1 and not brief:
        return CriticVerdict(choice=0)
    verdict = client.complete(
        messages=build_messages(manuscript, drafts, brief, genre),
        response_model=CriticVerdict,
        role="critic",
    )
    if not 0 <= verdict.choice < len(drafts):
        return verdict.model_copy(update={"choice": 0})
    return verdict
