"""Record every prompt a fixed offline run sends, for the genre snapshot test.

Regenerate with `uv run python tests/prompt_capture.py` and review the diff.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

from pydantic import BaseModel

SNAPSHOT = Path(__file__).parent / "data" / "mystery_prompts.json"


def capture(tmp: Path) -> list[dict[str, Any]]:
    from novelforge.llm.fake import FakeLLMClient
    from novelforge.pipeline import run_baseline, run_plan, run_scene
    from novelforge.roles.critic import CriticVerdict
    from novelforge.roles.guess_judge import GuessVerdict, LLMGuessJudge
    from novelforge.roles.prose import Prose, SceneDeck
    from novelforge.roles.reviser import revise_scene
    from novelforge.roles.themes import StoryCore, draft_core
    from novelforge.schema.canon import Canon, RevealPlanItem, Secret
    from novelforge.schema.reader import Persona, ReaderGuess, ReaderReport
    from novelforge.schema.scene import SceneCard
    from novelforge.schema.state import BookState
    from novelforge.schema.story import (
        Character,
        Pitch,
        PitchDeck,
        PitchScore,
        PlausibilityReport,
        StoryBible,
        Theme,
    )
    from novelforge.store import load_book, load_cards
    from novelforge.view.filter import build_writer_view

    story = StoryBible(
        hook="聋孩子是唯一的目击者",
        core="扳回一城",
        themes=[Theme(id="T-1", question="没人肯听的证词还算不算证词？", arc=["不说", "开口"])],
        protagonist_id="char-1",
        characters=[
            Character(id="char-1", name="闻笛", role="protagonist", edge="读唇"),
            Character(id="char-2", name="陈静", role="suspect", public_face="闺蜜"),
        ],
    )
    canon = Canon(
        title="雨棚",
        premise="暴雨夜",
        story=story,
        secrets=[
            Secret(id="S-1", title="凶手", text="陈静在楼道擦肩而过", probe_question="谁杀了她？")
        ],
        reveal_plan=[RevealPlanItem(secret_id="S-1", earliest_scene_id="sc-03", method="hint")],
    )
    card = SceneCard(
        scene_id="sc-01",
        title="雷",
        beats=["他摸窗看雷", "闪电里有人翻窗"],
        plants=["樟脑味"],
        misdirection=["校服"],
        directives=["他冲上楼"],
        theme_beat="他报了警",
        reader_feeling="心里一紧",
        ending_hook="袖口有血",
    )

    def respond(messages: list[dict[str, str]], model: type[BaseModel]) -> BaseModel | None:
        if model is PitchDeck:
            return PitchDeck(pitches=[Pitch(hook="甲"), Pitch(hook="乙")])
        if model is PitchScore:
            return PitchScore(score=4)
        if model is Canon:
            return canon
        if model is PlausibilityReport:
            return PlausibilityReport()
        if model is SceneDeck:
            return SceneDeck(scenes=[card, card, card])
        if model is Prose:
            return Prose(text="雷声闷着。\n他冲上楼。\n袖口有血。")
        if model is CriticVerdict:
            return CriticVerdict(choice=0, notes=["开头慢一点"], theme_note="他开口了")
        if model is ReaderReport:
            return ReaderReport(
                persona_id="p",
                tension="high",
                guesses=[ReaderGuess(probe_id="S-1", guess="不知道")],
            )
        if model is GuessVerdict:
            return GuessVerdict(match="wrong")
        if model is StoryCore:
            return StoryCore(core="爽", themes=[Theme(id="T-1", question="谁信他？")])
        return None

    client = FakeLLMClient(responder=respond)
    judge = LLMGuessJudge(client)
    people = [Persona(id="p", name="推理迷", traits=["爱猜"])]
    run_plan("demo", "暴雨夜", client, judge, root=tmp, scenes=3, personas=people)
    directory = tmp / "projects" / "demo"
    book = load_book(directory) or BookState(canon=canon)
    cards = load_cards(directory)
    run_scene(book, cards[0], [c.scene_id for c in cards], client, judge, people, drafts=2)
    view = build_writer_view(BookState(canon=canon), card)
    revise_scene(view, "雷声闷着。\n他冲上楼。", ["篇幅太短"], client)
    revise_scene(view, "雷声闷着。\n他冲上楼。\n袖口。", ["style"], client, only_paragraphs=[1])
    draft_core(canon.model_copy(update={"story": StoryBible()}), client, scenes=3)
    run_baseline("demo", "暴雨夜", client, root=tmp, scenes=3)
    return [
        {"role": call["role"], "model": call["response_model"], "messages": call["messages"]}
        for call in client.calls
    ]


if __name__ == "__main__":
    import tempfile

    os.environ.setdefault("LITELLM_LOCAL_MODEL_COST_MAP", "True")
    with tempfile.TemporaryDirectory() as folder:
        calls = capture(Path(folder))
    SNAPSHOT.parent.mkdir(exist_ok=True)
    SNAPSHOT.write_text(json.dumps(calls, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    print(f"{len(calls)} calls -> {SNAPSHOT}")
