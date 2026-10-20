"""Chapter summaries, a short reader packet, and closed-question archival.

The reader simulator still receives only locked text. This module builds that
text: finished chapters become summaries, and the last few scenes stay whole.
Human review points are recorded and never block.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict

from novelforge.schema.canon import iter_secret_texts
from novelforge.schema.memory import ChapterSummary, GateStat, ReviewKind, ReviewMark
from novelforge.schema.reader import ReaderState
from novelforge.schema.scene import LockedScene, SceneCard
from novelforge.schema.state import BookState

CHAPTER_SIZE = 3
RECENT_SCENES = 3
OPENING_CHAPTERS = 3
EXCERPT_CHARS = 80

PROMPT_FOR_GATE: dict[str, str] = {
    "literal": "writer",
    "pov": "writer",
    "length": "writer",
    "pace": "writer",
    "style": "writer",
    "directive": "planner",
    "inference": "writer",
    "reveal": "writer",
    "hint": "planner",
    "tension": "writer",
    "skim": "writer",
    "hooks": "planner",
    "retention": "architect",
}


def prompt_for_gate(gate_id: str) -> str:
    """Which prompt to fix first when `gate_id` fails; genre gates name their own."""

    if gate_id in PROMPT_FOR_GATE:
        return PROMPT_FOR_GATE[gate_id]
    from novelforge.gates.registry import gate

    try:
        return gate(gate_id).prompt
    except KeyError:
        return "writer"


SUMMARY_PROMPT = """你在给已经写完的几场做章节摘要。

规则：
- 只写正文里已经发生的可见事件。
- 不要补充原因、身份、动机或正文没有写明的解释。
- 用一两句中文。不要标题。"""


class Summary(BaseModel):
    model_config = ConfigDict(extra="forbid")

    text: str = ""


def scrub_hidden(text: str, hidden: list[str]) -> str:
    cleaned = text
    for secret in hidden:
        if len(secret) >= 2:
            cleaned = cleaned.replace(secret, "")
    return " ".join(cleaned.split())


def hidden_texts(book: BookState) -> list[str]:
    return [text for _, text in iter_secret_texts(book.canon, set(book.revealed_secret_ids))]


def is_opening_scene(index: int) -> bool:
    return index // CHAPTER_SIZE < OPENING_CHAPTERS


def is_payoff(book: BookState, card: SceneCard) -> bool:
    if card.must_reveal:
        return True
    return any(
        item.method == "reveal" and item.earliest_scene_id == card.scene_id
        for item in book.canon.reveal_plan
    )


def note_review(book: BookState, kind: ReviewKind, scene_id: str = "") -> BookState:
    if any(mark.kind == kind and mark.scene_id == scene_id for mark in book.review_marks):
        return book
    marks = [*book.review_marks, ReviewMark(kind=kind, scene_id=scene_id)]
    return book.model_copy(update={"review_marks": marks})


def earlier_lines(
    scenes: list[LockedScene],
    summaries: list[ChapterSummary],
    *,
    recent: int = RECENT_SCENES,
) -> list[str]:
    """Summaries and short excerpts for scenes that fell out of the recent window."""

    if len(scenes) <= recent:
        return []
    older = scenes[:-recent]
    older_ids = {scene.scene_id for scene in older}
    lines: list[str] = []
    covered: set[str] = set()
    for summary in summaries:
        if summary.scene_ids and set(summary.scene_ids) <= older_ids and summary.text.strip():
            lines.append(summary.text.strip())
            covered.update(summary.scene_ids)
    for scene in older:
        if scene.scene_id in covered:
            continue
        excerpt = " ".join(scene.text.split())[:EXCERPT_CHARS]
        if excerpt:
            lines.append(excerpt)
    return lines


def reading_packet(
    manuscript: list[LockedScene],
    summaries: list[ChapterSummary],
    hidden: list[str] | None = None,
    *,
    recent: int = RECENT_SCENES,
) -> list[LockedScene]:
    """Chapter summaries plus the last `recent` scenes in full.

    The last scene is always the one just read, so skip spans still refer to it.
    Hidden secret text is removed from summaries and excerpts only.
    """

    if len(manuscript) <= recent:
        return list(manuscript)
    blocked = hidden or []
    older = manuscript[:-recent]
    recent_scenes = list(manuscript[-recent:])
    older_ids = {scene.scene_id for scene in older}
    head: list[LockedScene] = []
    covered: set[str] = set()
    for summary in summaries:
        if not summary.scene_ids or not set(summary.scene_ids) <= older_ids:
            continue
        text = scrub_hidden(summary.text, blocked)
        if text:
            head.append(LockedScene.lock(f"mem-{summary.chapter_id}", text))
        covered.update(summary.scene_ids)
    for scene in older:
        if scene.scene_id in covered:
            continue
        text = scrub_hidden(" ".join(scene.text.split())[:EXCERPT_CHARS], blocked)
        if text:
            head.append(LockedScene.lock(f"mem-{scene.scene_id}", text))
    return [*head, *recent_scenes]


def _pending_chapters(
    scenes: list[LockedScene], summaries: list[ChapterSummary]
) -> list[list[LockedScene]]:
    done = {scene_id for summary in summaries for scene_id in summary.scene_ids}
    pending = [scene for scene in scenes if scene.scene_id not in done]
    groups: list[list[LockedScene]] = []
    while len(pending) >= CHAPTER_SIZE:
        groups.append(pending[:CHAPTER_SIZE])
        pending = pending[CHAPTER_SIZE:]
    return groups


def _fallback_excerpt(scenes: list[LockedScene]) -> str:
    parts = [" ".join(scene.text.split())[:EXCERPT_CHARS] for scene in scenes]
    return " ".join(part for part in parts if part)


def summarize_chapter(scenes: list[LockedScene], client: Any) -> str:
    body = "\n\n".join(f"## {scene.scene_id}\n{scene.text}" for scene in scenes)
    summary = client.complete(
        messages=[
            {"role": "system", "content": SUMMARY_PROMPT},
            {"role": "user", "content": body},
        ],
        response_model=Summary,
        role="gate",
        scene_id=scenes[-1].scene_id if scenes else None,
    )
    return summary.text.strip() or _fallback_excerpt(scenes)


def apply_memory(book: BookState, client: Any) -> BookState:
    """Add one summary per finished chapter. Already summarized scenes stay put."""

    hidden = hidden_texts(book)
    summaries = list(book.summaries)
    for group in _pending_chapters(book.locked_scenes, summaries):
        text = scrub_hidden(summarize_chapter(group, client), hidden)
        if not text:
            text = scrub_hidden(_fallback_excerpt(group), hidden)
        if not text:
            continue
        summaries.append(
            ChapterSummary(
                chapter_id=f"ch-{len(summaries) + 1:02d}",
                scene_ids=[scene.scene_id for scene in group],
                text=text,
            )
        )
    if summaries == list(book.summaries):
        return book
    return book.model_copy(update={"summaries": summaries})


def archive_closed(
    previous: dict[str, ReaderState],
    current: dict[str, ReaderState],
    archived: list[str],
) -> list[str]:
    """Questions nobody is asking anymore leave the live list and stay on file."""

    still = {question for reader in current.values() for question in reader.open_questions}
    kept = list(archived)
    for reader in previous.values():
        for question in reader.open_questions:
            if question and question not in still and question not in kept:
                kept.append(question)
    return kept


def tally_gates(book: BookState, results: list[Any]) -> BookState:
    stats = {gate_id: stat.model_copy() for gate_id, stat in book.gate_stats.items()}
    for result in results:
        stat = stats.get(result.gate_id, GateStat())
        stats[result.gate_id] = stat.model_copy(
            update={
                "checks": stat.checks + 1,
                "failures": stat.failures + (0 if result.passed else 1),
            }
        )
    return book.model_copy(update={"gate_stats": stats})


def hottest_prompt(stats: dict[str, GateStat]) -> tuple[str, str] | None:
    ranked = sorted(
        stats.items(),
        key=lambda item: (-item[1].failures, -item[1].checks, item[0]),
    )
    for gate_id, stat in ranked:
        if stat.failures:
            return gate_id, prompt_for_gate(gate_id)
    return None


def format_gate_report(book: BookState) -> list[str]:
    lines = [f"读者模拟器调用 {book.reader_sim_calls} 次"]
    if not book.gate_stats:
        lines.append("还没有闸门记录")
    else:
        for gate_id, stat in sorted(book.gate_stats.items()):
            prompt = prompt_for_gate(gate_id)
            lines.append(
                f"{gate_id}  checks={stat.checks}  failures={stat.failures}  prompt={prompt}"
            )
        hot = hottest_prompt(book.gate_stats)
        if hot:
            lines.append(f"先改 {hot[1]}：{hot[0]} 失败最多")
        else:
            lines.append("没有闸门失败")
    if book.review_marks:
        noted = "、".join(f"{mark.kind}:{mark.scene_id or '-'}" for mark in book.review_marks)
        lines.append(f"人审记录（已跳过，未停）：{noted}")
    return lines
