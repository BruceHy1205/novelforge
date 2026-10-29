"""Planner: Canon in, scene cards out. Directives may only describe visible behavior."""

from __future__ import annotations

from typing import Any

from novelforge.genres import Genre, fill, resolve
from novelforge.pacing.pace import apply_pacing
from novelforge.roles.behavior import apply_behavior
from novelforge.roles.prose import SceneDeck
from novelforge.schema.canon import Canon, hidden_secret_ids, iter_secret_texts
from novelforge.schema.scene import BEAT_FIELDS, CRAFT_FIELDS, SceneCard

SYSTEM_TEMPLATE = """你是<<identity>>。你知道全部真相（Canon 里的秘密），写手不知道。
根据 Canon 写出 {scenes} 场场景卡，每场是一整章（两千字以上），不要写正文。

<<mission>>

先读 story.core、story.themes、story.approach：这是这本书为什么而写、怎么写。
每一章都要喂 core 那种感觉，都要跑一圈 approach.engine，并且一章比一章升级。
themes 的 arc 要分摊到各章：主题只通过主角的选择、代价和关系变化出现，不靠人物讲道理。
approach.motifs 要在不同章节重复出现，每次出现意义都往前走一步。

每场包含：
- scene_id：sc-01 起依次编号
- title、beat_purpose、setting
- pov_character_id：用 story.characters 里的 id，默认是主角
- must_reveal / must_withhold：只放秘密 id，不放秘密原文
- hint_budget：none、light、moderate、heavy 之一
- reader_want（期待）：读完上一章，读者此刻具体想看到什么。具体到一件事。
- obstacle（压抑）：这一章怎么拖住它。主角在接近，有代价，还拿不到。
- payoff（释放）：这一章兑现的一笔小账。
- state_change：兑现之后什么变了（<<stakes>>）。
- theme_beat：这一章在哪个主题上走了一步，写成主角的一个具体选择或代价，
  以及它让主角对主题追问的回答怎样变了。一两句，不写结论性的道理。
- reader_feeling：读完这一章读者应该感到什么，要和 story.core 同向（可以是它的变奏）。
- beats：这一章的起承转合，四到六条，每条一两句，写成可以展开成几段正文的叙事单元。
<<beats>>
<<craft>>
- directives：这一章必须发生的事件，最多四条。只写看得见的事，不写原因、身份、动机。
  带“因为 / 所以 / 其实”的半句会被删掉。不要把每个动作都列成指令，节奏交给 beats。
- ending_hook：除最后一场外，断在变化发生的那一刻：发现、误判、代价或不可撤回的决定。
  写成一句短的可见事件，不要总结。
- answers_hook：若上一场有 ending_hook，这一章开头附近要碰到那件事。没有就留空。

前三章是黄金三章：
<<opening>>

不要在任何写手可见的字段里粘贴秘密原文、<<no_spoil>>。
pace、length、tension_target 由程序按张力曲线覆盖，你不用填。
hint 那场要在 plants 里安排一个可见的异常。reveal 那场的 must_reveal 放该秘密 id。"""

OPENING_TASKS: tuple[str, ...] = ("入局", "加压", "承诺")
PLAN_BATCH = 3


def system_prompt(genre: Genre | None = None) -> str:
    rules = resolve(genre)
    prompt = fill(SYSTEM_TEMPLATE, rules, "planner")
    if rules.beat_fields:
        lines = [f"- {name}：{text}" for name, text in rules.beat_fields.items()]
        prompt += (
            "\n\n本题材的专属节拍写进 genre_beats（键名照抄，每个键是一到三条可见的事）：\n"
            + "\n".join(lines)
        )
    return prompt


SYSTEM_PROMPT = system_prompt()


def plan_scenes(
    canon: Canon,
    client: Any,
    *,
    scenes: int = 8,
    genre: Genre | None = None,
    repair: str = "",
    scenes_per_batch: int = PLAN_BATCH,
) -> list[SceneCard]:
    """Plan in batches so a thinking model's reasoning does not hit the output cap.

    `scenes_per_batch` is how many cards one planner call writes. The default
    (`PLAN_BATCH`) is 3. `repair` is a rejection from the genre's card audit
    and goes into every batch.
    """

    if scenes_per_batch < 1:
        raise ValueError("scenes_per_batch must be at least 1")
    rules = resolve(genre)
    planned: list[SceneCard] = []
    while len(planned) < scenes:
        first = len(planned) + 1
        last = min(scenes, len(planned) + scenes_per_batch)
        user = canon.model_dump_json()
        if planned:
            earlier = SceneDeck(scenes=planned).model_dump_json()
            user += f"\n\n已经规划好的场景卡（承接它们，不要重写）：\n{earlier}"
        user += f"\n\n这一次只写 sc-{first:02d} 到 sc-{last:02d}，共 {last - first + 1} 张。"
        if repair:
            user += "\n\n上一版场景卡被退回，必须改掉：\n" + repair
        deck = client.complete(
            messages=[
                {"role": "system", "content": system_prompt(rules).format(scenes=scenes)},
                {"role": "user", "content": user},
            ],
            response_model=SceneDeck,
            role="planner",
        )
        batch = list(deck.scenes)[: last - first + 1]
        if not batch:
            break
        planned = number_scenes([*planned, *batch])
    cards = number_scenes(scrub_secret_text(planned, canon))[:scenes]
    cards = [apply_behavior(card, canon) for card in cards]
    cards = [_keep_beat_fields(card, rules) for card in cards]
    return apply_pacing(
        open_with_protagonist(cards, canon), knots=rules.knots, budget=rules.length_budget
    )


def _keep_beat_fields(card: SceneCard, genre: Genre) -> SceneCard:
    beats = {name: card.genre_beats[name] for name in genre.beat_fields if name in card.genre_beats}
    return card if beats == card.genre_beats else card.model_copy(update={"genre_beats": beats})


def open_with_protagonist(cards: list[SceneCard], canon: Canon) -> list[SceneCard]:
    """Fill the golden-three tasks and default the viewpoint to the protagonist."""

    hero = canon.story.protagonist()
    known = {person.id for person in canon.story.characters}
    filled: list[SceneCard] = []
    for index, card in enumerate(cards):
        update: dict[str, str] = {}
        if index < len(OPENING_TASKS) and not card.opening_task:
            update["opening_task"] = OPENING_TASKS[index]
        if hero is not None and card.pov_character_id not in known:
            update["pov_character_id"] = hero.id
        filled.append(card.model_copy(update=update) if update else card)
    return filled


def replan_scene(canon: Canon, card: SceneCard, client: Any, *, note: str = "") -> SceneCard:
    """Replace one card's directives after a leak or a failed gate. Returns one card."""

    deck = client.complete(
        messages=[
            {
                "role": "system",
                "content": (
                    "重写这一场的 directives。只保留可见的动作和对话，不要写原因和秘密。"
                    + (f"\n补充：{note}" if note else "")
                ),
            },
            {
                "role": "user",
                "content": card.model_dump_json(),
            },
        ],
        response_model=SceneDeck,
        role="planner",
        scene_id=card.scene_id,
    )
    directives = list(deck.scenes[0].directives) if deck.scenes else []
    fresh = card.model_copy(update={"directives": directives})
    return apply_behavior(scrub_secret_text([fresh], canon)[0], canon)


def number_scenes(cards: list[SceneCard]) -> list[SceneCard]:
    return [
        card.model_copy(update={"scene_id": f"sc-{index:02d}"})
        for index, card in enumerate(cards, start=1)
    ]


def scrub_secret_text(cards: list[SceneCard], canon: Canon) -> list[SceneCard]:
    """Drop hidden answers from writer-visible fields.

    A secret listed in this card's `must_reveal` may stay: the writer has to
    be able to pay it off. Hidden secret ids are stripped everywhere.
    """

    cleaned: list[SceneCard] = []
    for card in cards:
        unlocked = set(card.must_reveal)
        texts = [text for _, text in iter_secret_texts(canon, unlocked)]
        ids = hidden_secret_ids(canon, unlocked)
        directives = _keep_lines(card.directives, texts, ids)
        needles = [*texts, *ids]
        cleaned.append(
            card.model_copy(
                update={
                    "title": _strip_needles(card.title, needles),
                    "beat_purpose": _strip_needles(card.beat_purpose, needles),
                    "setting": _strip_needles(card.setting, needles),
                    "ending_hook": _strip_needles(card.ending_hook, needles),
                    "answers_hook": _strip_needles(card.answers_hook, needles),
                    **{
                        name: _strip_needles(str(getattr(card, name)), needles)
                        for name in BEAT_FIELDS
                        if name != "opening_task"
                    },
                    "directives": directives,
                    **{
                        name: _keep_lines(list(getattr(card, name)), texts, ids)
                        for name in CRAFT_FIELDS
                    },
                    "genre_beats": {
                        name: _keep_lines(list(lines), texts, ids)
                        for name, lines in card.genre_beats.items()
                    },
                }
            )
        )
    return cleaned


def _keep_lines(lines: list[str], texts: list[str], ids: list[str]) -> list[str]:
    """Drop a line that carries hidden text; strip hidden ids from the rest."""

    kept = [
        _strip_needles(line, ids)
        for line in lines
        if line and not any(secret and secret in line for secret in texts)
    ]
    return [line for line in kept if line]


def _strip_needles(value: str, needles: list[str]) -> str:
    cleaned = value
    for needle in needles:
        if needle:
            cleaned = cleaned.replace(needle, "")
    return " ".join(cleaned.split())
