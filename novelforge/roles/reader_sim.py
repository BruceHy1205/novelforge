"""Reader simulator.

Constitutional constraint: the simulator receives only locked manuscript text,
a persona, and public probe questions. Canon, SceneCard, and BookState must
never appear as parameters.

Prompt v2. The caller may pass chapter summaries (scene ids starting with
``mem-``) plus the last few scenes in full. v1 was the full manuscript.
Recalibrating v2 against human readers is skipped; do not block on it.
"""

from __future__ import annotations

from typing import Any

from novelforge.llm.fake import FakeLLMClient
from novelforge.schema.canon import Canon, iter_secret_texts
from novelforge.schema.reader import Persona, ReaderGuess, ReaderProbe, ReaderReport, SkipSpan
from novelforge.schema.scene import LockedScene
from novelforge.text import split_paragraphs

PROMPT_VERSION = "reader-sim-v2"

SYSTEM_PROMPT = """你在扮演一位正在逐场阅读小说的真实读者，不是编辑，也不是评论家。

读者画像：
{persona}

规则：
1. 只根据已读正文推断。即使你觉得认出了这部作品，也不要使用正文以外的知识。
2. 你的报告描述的是“刚读完最新一场时”的状态，不是读完全书后的回顾。
3. 对每个问题给出你此刻最可能的猜测（可以是“不知道”），以及信心档位：
   - none：完全没有头绪，或没想过这个问题
   - hint：隐约觉得某个方向，但说不出依据
   - suspect：有明确的怀疑对象和至少一条依据
   - certain：基本确定，只等书里确认
4. wants_to_know：此刻最想知道的 1–3 件事，用读者自己的话写。
5. skip_spans：只针对最新一场，列出按你的画像会想跳过的段落（用段落编号，含首尾）。没有就留空。
6. tension：最新一场让你多想继续读下去：flat / low / medium / high。
7. 不要为了显得聪明而夸大信心，也不要为了显得谨慎而压低信心。
8. 标记为「前文摘要」的部分是更早章节的压缩，不是全文。
   不要根据摘要发明摘要里没有的细节。跳读只针对最新一场全文。
9. would_continue：你是在网文平台上免费试读。读完最新一场，你会不会马上点下一章？
   诚实回答。只是“现场描写得清楚”不够；没有让你在乎的人、没有你想看到的事，就答 false。
   continue_reason 用一句话说为什么点或不点。
10. craving：你此刻最想看到主角做成或遇到的一件具体的事。说不出就留空。
11. boring_paragraph：最新一场里你最想放下书的那一段的编号。没有就留空。"""


class UnsafeProbeError(ValueError):
    """A probe question contains hidden secret text."""


def describe_persona(persona: Persona) -> str:
    lines = [f"- 名称：{persona.name or persona.id}"]
    if persona.reading_style:
        lines.append(f"- 阅读方式：{persona.reading_style}")
    lines.extend(f"- {trait}" for trait in persona.traits)
    return "\n".join(lines)


def render_manuscript(manuscript: list[LockedScene]) -> str:
    blocks: list[str] = []
    for index, scene in enumerate(manuscript):
        latest = index == len(manuscript) - 1
        paragraphs = "\n".join(
            f"[¶{number}] {paragraph}"
            for number, paragraph in enumerate(split_paragraphs(scene.text))
        )
        blocks.append(f"{_heading(scene, latest)}\n{paragraphs}")
    return "\n\n".join(blocks)


def _heading(scene: LockedScene, latest: bool) -> str:
    if scene.scene_id.startswith("mem-"):
        label = f"前文摘要 {scene.scene_id}"
    else:
        label = f"场景 {scene.scene_id}"
    if latest:
        label += "（最新一场）"
    return f"## {label}"


def build_messages(
    manuscript: list[LockedScene],
    persona: Persona,
    probes: list[ReaderProbe],
) -> list[dict[str, str]]:
    questions = "\n".join(f"- {probe.probe_id}: {probe.question}" for probe in probes) or "（无）"
    latest = manuscript[-1].scene_id if manuscript else "（无）"
    user = (
        f"# 已读正文\n\n{render_manuscript(manuscript)}\n\n"
        f"# 问题\n{questions}\n\n"
        f"最新一场：{latest}"
    )
    return [
        {"role": "system", "content": SYSTEM_PROMPT.format(persona=describe_persona(persona))},
        {"role": "user", "content": user},
    ]


def simulate_reader(
    manuscript: list[LockedScene],
    persona: Persona,
    probes: list[ReaderProbe] | None = None,
    *,
    client: Any | None = None,
) -> ReaderReport:
    """Report what this persona believes right after the last scene in `manuscript`."""

    probes = probes or []
    llm = client or FakeLLMClient(defaults={"persona_id": persona.id})
    raw = llm.complete(
        messages=build_messages(manuscript, persona, probes),
        response_model=ReaderReport,
        role="reader_sim",
        scene_id=manuscript[-1].scene_id if manuscript else None,
    )
    return _sanitize(raw, manuscript, persona, probes)


def _sanitize(
    report: ReaderReport,
    manuscript: list[LockedScene],
    persona: Persona,
    probes: list[ReaderProbe],
) -> ReaderReport:
    """Pin identity fields and drop anything the model was not asked about."""

    probe_ids = [probe.probe_id for probe in probes]
    by_probe: dict[str, ReaderGuess] = {}
    for guess in report.guesses:
        if guess.probe_id in probe_ids and guess.probe_id not in by_probe:
            by_probe[guess.probe_id] = guess
    guesses = [by_probe.get(pid, ReaderGuess(probe_id=pid)) for pid in probe_ids]

    skip_spans: list[SkipSpan] = []
    boring = report.boring_paragraph
    if manuscript:
        latest = manuscript[-1]
        paragraph_count = len(split_paragraphs(latest.text))
        if boring is not None and boring >= paragraph_count:
            boring = None
        for span in report.skip_spans:
            if span.scene_id != latest.scene_id:
                continue
            if max(span.paragraph_start, span.paragraph_end) >= paragraph_count:
                continue
            skip_spans.append(span)

    return report.model_copy(
        update={
            "persona_id": persona.id,
            "last_scene_id": manuscript[-1].scene_id if manuscript else None,
            "guesses": guesses,
            "skip_spans": skip_spans,
            "boring_paragraph": boring if manuscript else None,
        }
    )


def probes_from_canon(canon: Canon, revealed: set[str] | None = None) -> list[ReaderProbe]:
    """Build public probes for hidden secrets. Called on the canon side, not by the simulator."""

    revealed = revealed or set()
    secret_texts = [text for _, text in iter_secret_texts(canon, revealed)]
    probes: list[ReaderProbe] = []
    for secret in canon.secrets:
        if secret.id in revealed or not secret.probe_question:
            continue
        if any(text and text in secret.probe_question for text in secret_texts):
            raise UnsafeProbeError(f"probe for {secret.id} contains hidden secret text")
        probes.append(ReaderProbe(probe_id=secret.id, question=secret.probe_question))
    return probes
