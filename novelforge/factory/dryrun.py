"""Offline client for the factory's dry-run mode: placeholder canon, cards, and prose.

Every role answers without a model so the whole outline → trial → full path can
be exercised from the console. The text is filler, not a story.
"""

from __future__ import annotations

import hashlib
import json
import re

from pydantic import BaseModel

from novelforge.llm.fake import FakeLLMClient
from novelforge.roles.prose import Prose, SceneDeck
from novelforge.schema.canon import Canon, RevealPlanItem, Secret
from novelforge.schema.scene import SceneCard
from novelforge.schema.story import Character, StoryBible

BEATS = {
    "face_slap": ["演练：对手当众吃瘪"],
    "gain": ["演练：拿到一块令牌"],
    "reaction": ["演练：围观的人改了口"],
    "spent": ["演练：用掉一块令牌"],
}


def _tag(text: str) -> str:
    return hashlib.sha1(text.encode("utf-8")).hexdigest()[:4]


def _canon(idea: str) -> Canon:
    head = idea.strip().splitlines()[0][:12] if idea.strip() else "演练"
    return Canon(
        title=f"{head}（演练{_tag(idea)}）",
        premise=idea.strip() or "演练用的前提。",
        story=StoryBible(
            hook="演练钩子：渡口一夜之间封了。",
            background="民国年间的江边渡口。封渡的告示贴在门板上，账房连夜离开，镇上的人只敢在茶馆里猜。",
            concept="林舟能看见别人看不见的一笔账。每对上一次，对方就要当众认一次。",
            core="演练核心：每一章都离真相近一步。",
            protagonist_id="c1",
            characters=[
                Character(id="c1", name="林舟", role="protagonist", want="找到失踪的哥哥"),
                Character(id="c2", name="周先生", role="suspect", public_face="账房"),
                Character(id="c3", name="赵三", role="antagonist", public_face="帮主"),
            ],
        ),
        secrets=[
            Secret(
                id="S-1",
                title="演练秘密一",
                text="演练真相甲乙丙",
                probe_question="谁最可疑？",
                known_by=["周先生"],
            ),
            Secret(
                id="S-2",
                title="演练秘密二",
                text="演练真相丁戊己",
                probe_question="渡口为什么封？",
                known_by=["赵三"],
            ),
        ],
        reveal_plan=[RevealPlanItem(secret_id="S-1", method="withhold")],
    )


_BATCH = re.compile(r"这一次只写 sc-(\d+) 到 sc-(\d+)")


def _span(user: str) -> tuple[int, int]:
    """Read the planner's `sc-N 到 sc-M` range. Chapter numbers can pass 99."""

    match = _BATCH.search(user)
    if match is None:
        return 1, 3
    start = int(match.group(1))
    last = int(match.group(2))
    if start < 1 or last < start:
        return 1, 3
    return start, last - start + 1


def _deck(user: str) -> SceneDeck:
    start, count = _span(user)
    cards = [
        SceneCard(
            scene_id=f"sc-{start + index:02d}",
            title=f"演练第{start + index}章",
            beat_purpose="演练推进",
            pov_character_id="c1",
            setting="渡口",
            ending_hook="灯灭了",
            answers_hook="灯灭了",
            beats=["林舟推门进去"],
            genre_beats={name: list(lines) for name, lines in BEATS.items()},
        )
        for index in range(count)
    ]
    return SceneDeck(scenes=cards)


def _scene_length(messages: list[dict[str, str]]) -> int:
    decoder = json.JSONDecoder()
    for message in reversed(messages):
        content = message["content"].lstrip()
        if not content.startswith("{"):
            continue
        try:
            data, _ = decoder.raw_decode(content)
        except ValueError:
            continue
        scene = data.get("scene", data)
        if isinstance(scene, dict) and "length" in scene:
            return int(scene["length"])
    return 600


def _prose(messages: list[dict[str, str]]) -> Prose:
    length = max(60, _scene_length(messages))
    line = "演练正文：林舟推开门，雨还在下，灯灭了。"
    paragraphs = max(1, length // (len(line) * 3))
    text = "\n\n".join(line * 3 for _ in range(paragraphs))
    return Prose(text=text)


def dry_run_client() -> FakeLLMClient:
    def respond(messages: list[dict[str, str]], model: type[BaseModel]) -> BaseModel | None:
        user = next((m["content"] for m in messages if m["role"] == "user"), "")
        name = model.__name__
        if name == "Canon":
            return _canon(user.split("\n\n")[0])
        if name == "SceneDeck":
            return _deck(user)
        if name == "Prose":
            return _prose(messages)
        return None

    return FakeLLMClient(responder=respond)
