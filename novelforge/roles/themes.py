"""What the book is for: core feeling, themes, and the writing approach.

The architect writes them with the Canon. A Canon saved without them gets
them drafted on top. Either way they are public text the writer reads, so a
blind reader must not be able to guess a hidden secret from them.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from novelforge.genres import Genre, fill, resolve
from novelforge.roles.architect import scrub_story
from novelforge.roles.directives import leaking_secret_ids
from novelforge.roles.guess_judge import GuessJudge
from novelforge.schema.canon import Canon, iter_secret_texts
from novelforge.schema.reader import Persona
from novelforge.schema.story import Approach, StoryBible, Theme

PROMPT_TEMPLATE = """你是<<identity>>。Canon 已经定了（你能看到全部真相），现在要定这本书“为什么而写”。

- core：核心体验，一句话。读者每章回来追的那种感觉，要具体到情绪。
<<core>>
- themes：一到三个主题。每个写 id（T-1…）、question（写成问题）、tension（两种都有道理的回答）、
  arc（三到五步，主角对这个问题的回答怎样随故事变化）。
<<guard>>
- approach：
  engine：叙事引擎，每章重复并升级的阅读动力。
  voice：叙述声音。
  motifs：两到四个反复出现的意象或物件，每次出现意义往前走一步。
  principles：两到四条写法原则。

这些内容写手都会看到，不能写秘密原文，不能暗示谜底。"""  # noqa: E501


class StoryCore(BaseModel):
    model_config = ConfigDict(extra="forbid")

    core: str = ""
    themes: list[Theme] = Field(default_factory=list)
    approach: Approach = Field(default_factory=Approach)


def has_core(story: StoryBible) -> bool:
    return bool(story.core and story.themes)


class StoryGap(BaseModel):
    """Only the public lines a genre may require when the architect left them blank."""

    model_config = ConfigDict(extra="forbid")

    core: str = ""
    engine: str = ""


GAP_PROMPT = """这本书的公开层有空缺。只补空着的项，已经写了的不要改，不要写秘密。

- core：读者每章回来追的那种感觉，一句话。
- engine：每章重复的阅读动力。写清主角做了什么，事情才往前走。

当前 core：{core}
当前 engine：{engine}

Canon：
{canon}"""


def fill_missing_story(canon: Canon, client: Any, *, scenes: int) -> Canon:
    """Fill a blank core or engine and leave themes that are already there."""

    story = canon.story
    if story.core and story.approach.engine:
        return canon
    gap = client.complete(
        messages=[
            {
                "role": "user",
                "content": GAP_PROMPT.format(
                    core=story.core or "（空）",
                    engine=story.approach.engine or "（空）",
                    canon=canon.model_dump_json(),
                ),
            }
        ],
        response_model=StoryGap,
        role="architect",
    )
    approach = story.approach
    if not approach.engine and gap.engine:
        approach = approach.model_copy(update={"engine": gap.engine})
    updated = story.model_copy(update={"core": story.core or gap.core, "approach": approach})
    texts = [text for _, text in iter_secret_texts(canon)]
    return canon.model_copy(update={"story": scrub_story(updated, texts, scenes)})


def draft_core(canon: Canon, client: Any, *, scenes: int, genre: Genre | None = None) -> Canon:
    """Fill core / themes / approach on a Canon that lacks them."""

    drafted = client.complete(
        messages=[
            {"role": "system", "content": fill(PROMPT_TEMPLATE, resolve(genre), "themes")},
            {"role": "user", "content": canon.model_dump_json()},
        ],
        response_model=StoryCore,
        role="architect",
    )
    story = canon.story.model_copy(
        update={"core": drafted.core, "themes": drafted.themes, "approach": drafted.approach}
    )
    texts = [text for _, text in iter_secret_texts(canon)]
    return canon.model_copy(update={"story": scrub_story(story, texts, scenes)})


def screen_core(
    canon: Canon,
    personas: list[Persona],
    client: Any,
    judge: GuessJudge,
) -> Canon:
    """Drop any theme, and the approach, that lets a blind reader guess a secret."""

    story = canon.story

    def leaks(lines: list[str]) -> bool:
        return bool(leaking_secret_ids(lines, canon, personas, client, judge))

    themes = [
        theme for theme in story.themes if not leaks([theme.question, theme.tension, *theme.arc])
    ]
    approach = story.approach
    core = story.core
    if leaks([core, *approach.texts()]):
        core, approach = "", Approach(voice=approach.voice, principles=list(approach.principles))
    screened = story.model_copy(update={"themes": themes, "core": core, "approach": approach})
    return canon.model_copy(update={"story": screened})
