"""Reviser. Style and POV fixes touch only the bad paragraphs.

Scene-level failures (length, pace, skim, hooks, leaks) still rewrite the scene.
Reasons must already be free of secret text.
"""

from __future__ import annotations

from typing import Any

from novelforge.gates.pov import pov_problem_indexes
from novelforge.gates.style import style_problem_indexes
from novelforge.genres import Genre, fill, resolve
from novelforge.pacing.pace import craft_block
from novelforge.roles.prose import ParagraphFixes, Prose
from novelforge.schema.canon import Secret
from novelforge.schema.gate import GateResult
from novelforge.schema.reader import POVState
from novelforge.schema.scene import WriterView
from novelforge.text import split_paragraphs

LOCAL_GATES = frozenset({"style", "pov"})

SYSTEM_TEMPLATE = """你是修订者。根据场景视图重写这一场，处理列出的问题。

规则：
- 若只列出了段落编号，只重写那些段，其他段一个字都不要改。
- 没有段落编号时，整场重写，不要只写修改说明。
- 仍然只能使用视图里的信息。不要新增原因、身份或秘密。
- 保留原稿的铺垫、氛围、对话和主角的内心，不要把整章改成动作清单，不要明显缩短篇幅。
<<leak>>
- 若问题是张力不够：让这一章的冲突更直接，转折更早到来。
<<hint>>
<<skim>>
- 若问题是篇幅太短：整章重写，按 beats 逐条展开没写开的叙事单元（场景、对话、主角的反应），
  写到要求的字数，不要灌水；太长就删掉重复。
- 若问题含 theme 或核心体验：让 scene.theme_beat 落成主角一个具体的选择或代价，
  让 scene.reader_feeling 在高潮那几段被读者感到。不要加感悟和说教。
- 保持 story.approach.voice 的叙述声音，不要改成别的腔调。
- 若问题含 ending hook：最后一段写出视图里的 ending_hook。
- 若问题含 previous hook 或 previous question：写出视图里的 answers_hook，并回应读者还在问的事。
- 若问题含 readers would stop：读者不想追。让主角更早出场、更早被卷进去，
  把 reader_want 写成读者看得见的欲望，把 obstacle 写成主角付出的代价，
  在结尾前兑现 payoff。读者说了最想看到的事，就往那个方向推，不要再加现场描写。
- 写法以本说明为准。"""


def system_prompt(genre: Genre | None = None) -> str:
    return fill(SYSTEM_TEMPLATE, resolve(genre), "reviser")


SYSTEM_PROMPT = system_prompt()


def revision_indexes(
    draft: str,
    results: list[GateResult],
    *,
    samples: list[str] | None = None,
    pov: POVState | None = None,
    secrets: list[Secret] | None = None,
    others: list[POVState] | None = None,
) -> list[int] | None:
    """Paragraphs to rewrite, or None when the whole scene has to change."""

    failed = [result for result in results if not result.passed]
    if not failed or any(result.gate_id not in LOCAL_GATES for result in failed):
        return None
    paragraphs = split_paragraphs(draft)
    reasons = [reason for result in failed for reason in result.reasons]
    indexes = set(style_problem_indexes(draft, reasons, samples))
    if any(result.gate_id == "pov" for result in failed):
        indexes.update(pov_problem_indexes(draft, pov, secrets, others))
    if not indexes or len(indexes) >= len(paragraphs):
        return None
    return sorted(indexes)


def _splice(draft: str, fixes: ParagraphFixes, allowed: set[int]) -> str:
    paragraphs = split_paragraphs(draft)
    for fix in fixes.fixes:
        if fix.index in allowed and fix.index < len(paragraphs) and fix.text.strip():
            paragraphs[fix.index] = fix.text.strip()
    return "\n".join(paragraphs)


def revise_scene(
    view: WriterView,
    draft: str,
    reasons: list[str],
    client: Any,
    *,
    only_paragraphs: list[int] | None = None,
    genre: Genre | None = None,
) -> str:
    craft = craft_block(str(view.scene.pace), view.scene.length, resolve(genre).pace_craft)
    if only_paragraphs:
        numbered = "\n".join(f"- 第 {index} 段" for index in only_paragraphs)
        fixes = client.complete(
            messages=[
                {"role": "system", "content": f"{system_prompt(genre)}\n\n{craft}"},
                {
                    "role": "user",
                    "content": "\n".join(
                        [
                            view.model_dump_json(),
                            "",
                            "只改这些段：",
                            numbered,
                            "问题：",
                            *(f"- {reason}" for reason in reasons),
                            "",
                            "当前正文：",
                            draft,
                        ]
                    ),
                },
            ],
            response_model=ParagraphFixes,
            role="reviser",
            scene_id=view.scene.scene_id,
        )
        return _splice(draft, fixes, set(only_paragraphs))
    prose = client.complete(
        messages=[
            {"role": "system", "content": f"{system_prompt(genre)}\n\n{craft}"},
            {
                "role": "user",
                "content": "\n".join(
                    [
                        view.model_dump_json(),
                        "",
                        "问题：",
                        *(f"- {reason}" for reason in reasons),
                        "",
                        "当前正文：",
                        draft,
                    ]
                ),
            },
        ],
        response_model=Prose,
        role="reviser",
        scene_id=view.scene.scene_id,
    )
    return prose.text.strip()
