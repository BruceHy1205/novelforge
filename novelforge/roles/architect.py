"""Architect: an idea becomes a Canon. This role is allowed to see secrets.

Three steps. Pitch three hooks and let reader personas pick the one they would
open. Draft the Canon around it, story layer first. Then a gate-side check that
the method works in the real world and the solution is fair; redraft once.
"""

from __future__ import annotations

from typing import Any

from novelforge.genres import Genre, fill, resolve
from novelforge.schema.canon import Canon, RevealPlanItem, Secret, iter_secret_texts
from novelforge.schema.reader import Persona
from novelforge.schema.story import (
    Character,
    Expectation,
    Pitch,
    PitchDeck,
    PitchScore,
    PlausibilityReport,
    StoryBible,
)

PITCH_COUNT = 3

PITCH_TEMPLATE = """你是<<identity>>。根据创意给出 {count} 个不同的开书方案。

每个方案：
- hook：一句话高概念。读者看完要“哇”一声，而不是“哦”。
- selling_point：这本书持续给读者的甜头（每章都想看的东西）。
- protagonist：主角是谁、处境多糟、想要什么、手里有什么别人没有的优势或信息差。
<<protagonist>>
- opening_image：第一章第一段的画面，必须已经出事。

三个方案要真的不同：主角、优势、卖点至少两项不同。不要写谜底。"""

PITCH_SCORE_PROMPT = """你是一位网文读者。下面是一本书的简介。

读者画像：
{persona}

只凭简介回答：你会不会点开第一章（would_open），打 1 到 5 分（5 是马上点开），
reason 用一句话说为什么。无聊、看过太多次、主角没有处境，都要压分。

简介：
{pitch}"""

SYSTEM_TEMPLATE = """你是<<identity>>。根据创意和选定的开书方案写出作者全知的 Canon，不要写正文。

先写 story（全部是读者和写手都能看到的公开层，绝不能写谜底）：
- hook、selling_point、tone：沿用开书方案，可以打磨。
- background：故事背景。时代、地方、规矩，以及第一章开始前已经成立的局面。
  三五句，读者能看懂。不要写谜底，不要写成第一章正文。
- concept：核心设定。这本书立住的那一条规则或局面，读者记住这一句就知道这是哪本书。
  具体到能约束后文。不要写成情绪（那是 core），不要写谜底。
<<cast>>
- protagonist_id：主角的 id。
- expectations：1 条 main（全书主期待）+ 2 条 side（支线期待），promise 写读者具体想看到的事，
  payoff_scene_id 写兑现场次。

再定这本书“为什么而写”（同样是公开层，写手会照着写）：
<<why>>

再写秘密：
- <<secret_count>>。每个秘密有 id（S-1、S-2…）、title、text、probe_question。
<<secrets>>
- probe_question 是问读者的话，例如“谁动了那杯茶？”。问题里不得出现 text 里的答案。
- reveal_plan 与秘密一一对应。method 只能是 withhold、hint、reveal。
- earliest_scene_id 用 sc-01 这种编号，且必须落在一共 {scenes} 场之内（sc-01 到 sc-{last}）。
- hint 表示读者到那一场应该开始起疑，但还不能确定。reveal 表示那一场可以让读者确定。
- withhold 表示在最早那场之前（以及该场）都还不能让读者看出来。
- author_rationale 只写给作者，不要写进后文。"""


def pitch_prompt(genre: Genre | None = None) -> str:
    return fill(PITCH_TEMPLATE, resolve(genre), "pitch")


def system_prompt(genre: Genre | None = None) -> str:
    return fill(SYSTEM_TEMPLATE, resolve(genre), "architect")


def draft_canon(
    idea: str,
    client: Any,
    *,
    scenes: int = 8,
    personas: list[Persona] | None = None,
    genre: Genre | None = None,
) -> Canon:
    rules = resolve(genre)
    pitch = choose_pitch(idea, client, personas or [], genre=rules)
    canon = _draft(idea, pitch, client, scenes, genre=rules)
    problems = structural_problems(canon, rules)
    if not problems:
        report = check_plausibility(canon, client, genre=rules)
        if not (report.plausible and report.fair_play):
            problems = list(report.problems)
        if rules.audit_edge:
            from novelforge.roles.audit import review_text

            problems = [
                *problems,
                *review_text(rules.audit_edge, client, canon=canon.model_dump_json()),
            ]
    if problems:
        first = canon
        try:
            canon = _draft(idea, pitch, client, scenes, problems=problems, genre=rules)
        except TimeoutError:
            if structural_problems(first, rules):
                raise
            return first
        if rules.requires_secrets and not canon.secrets:
            raise IncompleteCanonError("; ".join(structural_problems(canon, rules)))
        if rules.audit_edge:
            from novelforge.roles.audit import PlanRejected, review_text

            remaining = structural_problems(canon, rules)
            if not remaining:
                remaining = review_text(rules.audit_edge, client, canon=canon.model_dump_json())
            if remaining:
                raise PlanRejected("；".join(remaining))
    return canon


class IncompleteCanonError(ValueError):
    """The architect returned a Canon the rest of the pipeline cannot check."""


def structural_problems(canon: Canon, genre: Genre | None = None) -> list[str]:
    """Without secrets nothing is hidden; without a cast the writer has no one to write."""

    rules = resolve(genre)
    story = canon.story
    problems: list[str] = []
    if rules.requires_secrets and not canon.secrets:
        problems.append("secrets 为空：真相要拆成 2 到 4 个秘密写进 secrets，不能只写在 premise")
    for role, label in rules.required_roles.items():
        present = (
            story.protagonist() is not None
            if role == "protagonist"
            else any(person.role == role for person in story.characters)
        )
        if not present:
            problems.append(f"story.characters 里没有{label}（role={role}）")
    if not story.hook:
        problems.append("story.hook 为空")
    return problems


def _draft(
    idea: str,
    pitch: Pitch | None,
    client: Any,
    scenes: int,
    *,
    problems: list[str] | None = None,
    genre: Genre | None = None,
) -> Canon:
    last = f"{scenes:02d}"
    user = idea.strip()
    if pitch is not None:
        user += "\n\n选定的开书方案：\n" + render_pitch(pitch)
    if problems:
        user += "\n\n上一版被退回，必须改掉：\n" + "\n".join(f"- {item}" for item in problems)
    canon = client.complete(
        messages=[
            {
                "role": "system",
                "content": system_prompt(genre).format(scenes=scenes, last=last),
            },
            {"role": "user", "content": user},
        ],
        response_model=Canon,
        role="architect",
    )
    return sanitize_canon(canon, scenes)


def render_pitch(pitch: Pitch) -> str:
    lines = [
        f"卖点：{pitch.hook}",
        f"持续甜头：{pitch.selling_point}",
        f"主角：{pitch.protagonist}",
        f"开篇画面：{pitch.opening_image}",
    ]
    return "\n".join(line for line in lines if not line.endswith("："))


def draft_pitches(
    idea: str, client: Any, *, count: int = PITCH_COUNT, genre: Genre | None = None
) -> list[Pitch]:
    deck = client.complete(
        messages=[
            {"role": "system", "content": pitch_prompt(genre).format(count=count)},
            {"role": "user", "content": idea.strip()},
        ],
        response_model=PitchDeck,
        role="architect",
    )
    return [pitch for pitch in deck.pitches if pitch.hook.strip()][:count]


def score_pitch(pitch: Pitch, persona: Persona, client: Any) -> PitchScore:
    from novelforge.roles.reader_sim import describe_persona

    prompt = PITCH_SCORE_PROMPT.format(persona=describe_persona(persona), pitch=render_pitch(pitch))
    return client.complete(
        messages=[{"role": "user", "content": prompt}],
        response_model=PitchScore,
        role="reader_sim",
    )


def choose_pitch(
    idea: str, client: Any, personas: list[Persona], *, genre: Genre | None = None
) -> Pitch | None:
    """Highest total score wins; a reader who would not open costs two points."""

    pitches = draft_pitches(idea, client, genre=genre)
    if not pitches:
        return None
    if not personas or len(pitches) == 1:
        return pitches[0]
    best: tuple[int, int] | None = None
    chosen = pitches[0]
    for index, pitch in enumerate(pitches):
        total = 0
        for persona in personas:
            score = score_pitch(pitch, persona, client)
            total += score.score - (0 if score.would_open else 2)
        key = (total, -index)
        if best is None or key > best:
            best, chosen = key, pitch
    return chosen


def check_plausibility(
    canon: Canon, client: Any, *, genre: Genre | None = None
) -> PlausibilityReport:
    rules = resolve(genre)
    if not canon.secrets and rules.requires_secrets:
        return PlausibilityReport()
    prompt = rules.prompt("plausibility")
    return client.complete(
        messages=[{"role": "user", "content": prompt.format(canon=canon.model_dump_json())}],
        response_model=PlausibilityReport,
        role="gate",
    )


def sanitize_canon(canon: Canon, scenes: int) -> Canon:
    """Repair ids, strip probe questions that contain the answer, scrub the story layer."""

    secrets: list[Secret] = []
    for index, secret in enumerate(canon.secrets, start=1):
        secret_id = secret.id or f"S-{index}"
        question = secret.probe_question or "这一场里，谁最不对劲？"
        if any(text and text in question for _, text in iter_secret_texts(Canon(secrets=[secret]))):
            question = "这一场里，谁最不对劲？"
        secrets.append(secret.model_copy(update={"id": secret_id, "probe_question": question}))
    known = {secret.id for secret in secrets}
    plan: list[RevealPlanItem] = []
    seen: set[str] = set()
    for item in canon.reveal_plan:
        if item.secret_id not in known or item.secret_id in seen:
            continue
        seen.add(item.secret_id)
        plan.append(
            item.model_copy(
                update={"earliest_scene_id": _clamp_scene(item.earliest_scene_id, scenes)}
            )
        )
    for secret in secrets:
        if secret.id not in seen:
            plan.append(
                RevealPlanItem(
                    secret_id=secret.id, earliest_scene_id=f"sc-{scenes:02d}", method="reveal"
                )
            )
    repaired = canon.model_copy(update={"secrets": secrets, "reveal_plan": plan})
    texts = [text for _, text in iter_secret_texts(repaired)]
    story = scrub_story(repaired.story, texts, scenes)
    return repaired.model_copy(update={"story": story})


def scrub_story(story: StoryBible, secret_texts: list[str], scenes: int) -> StoryBible:
    """The story layer is public. Remove any secret text that slipped in."""

    needles = sorted((text for text in secret_texts if len(text) >= 2), key=len, reverse=True)

    def clean(value: str) -> str:
        for needle in needles:
            value = value.replace(needle, "")
        return " ".join(value.split())

    def clean_lines(values: list[str]) -> list[str]:
        kept = [value for value in values if not any(needle in value for needle in needles)]
        return [line for line in (clean(value) for value in kept) if line]

    characters: list[Character] = []
    for index, person in enumerate(story.characters, start=1):
        fields = {
            name: clean(getattr(person, name))
            for name in (
                "name",
                "public_face",
                "want",
                "stake",
                "edge",
                "surface_motive",
                "surface_opportunity",
            )
        }
        characters.append(person.model_copy(update={"id": person.id or f"char-{index}", **fields}))
    expectations: list[Expectation] = []
    for index, item in enumerate(story.expectations, start=1):
        expectations.append(
            item.model_copy(
                update={
                    "id": item.id or f"E-{index}",
                    "promise": clean(item.promise),
                    "payoff_scene_id": _clamp_scene(item.payoff_scene_id, scenes),
                }
            )
        )
    protagonist_id = story.protagonist_id
    if protagonist_id not in {person.id for person in characters}:
        hero = next((person for person in characters if person.role == "protagonist"), None)
        protagonist_id = hero.id if hero is not None else ""
    themes = [
        theme.model_copy(
            update={
                "id": theme.id or f"T-{index}",
                "question": clean(theme.question),
                "tension": clean(theme.tension),
                "arc": clean_lines(theme.arc),
            }
        )
        for index, theme in enumerate(story.themes, start=1)
    ]
    approach = story.approach
    approach = approach.model_copy(
        update={
            "engine": clean(approach.engine),
            "voice": clean(approach.voice),
            "motifs": clean_lines(approach.motifs),
            "principles": clean_lines(approach.principles),
        }
    )
    return story.model_copy(
        update={
            "hook": clean(story.hook),
            "selling_point": clean(story.selling_point),
            "tone": clean(story.tone),
            "background": clean(story.background),
            "concept": clean(story.concept),
            "core": clean(story.core),
            "themes": [theme for theme in themes if theme.question],
            "approach": approach,
            "protagonist_id": protagonist_id,
            "characters": characters,
            "expectations": expectations,
        }
    )


def _clamp_scene(scene_id: str | None, scenes: int) -> str:
    if scene_id and scene_id.startswith("sc-"):
        number = scene_id.removeprefix("sc-")
        if number.isdigit() and 1 <= int(number) <= scenes:
            return f"sc-{int(number):02d}"
    return f"sc-{scenes:02d}"
