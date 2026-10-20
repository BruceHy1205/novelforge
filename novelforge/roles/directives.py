"""Reject directives that let a blind reader guess a hidden secret.

The simulator sees only the directive text, wrapped as a locked scene.
The judge on this side of the line compares the guess with the truth.
"""

from __future__ import annotations

from typing import Any

from novelforge.llm.role_client import RoleClient
from novelforge.roles.guess_judge import GuessJudge, effective_confidence
from novelforge.roles.planner import replan_scene
from novelforge.roles.reader_sim import probes_from_canon, simulate_reader
from novelforge.schema.canon import Canon
from novelforge.schema.reader import Persona
from novelforge.schema.scene import LockedScene, SceneCard


def leaking_secret_ids(
    directives: list[str],
    canon: Canon,
    personas: list[Persona],
    client: Any,
    judge: GuessJudge,
    *,
    allowed: set[str] | None = None,
) -> list[str]:
    text = "\n".join(line for line in directives if line).strip()
    if not text or not canon.secrets:
        return []
    unlocked = allowed or set()
    probes = probes_from_canon(canon, unlocked)
    secrets = {secret.id: secret for secret in canon.secrets}
    leaked: list[str] = []
    manuscript = [LockedScene.lock("directive", text)]
    for persona in personas:
        report = simulate_reader(manuscript, persona, probes, client=RoleClient(client, "gate"))
        for guess in report.guesses:
            secret = secrets.get(guess.probe_id)
            if secret is None or secret.id in unlocked:
                continue
            verdict = judge.judge(secret.id, secret.probe_question, secret.text, guess.guess)
            level = effective_confidence(verdict, guess.confidence)
            if level in {"suspect", "certain"} and secret.id not in leaked:
                leaked.append(secret.id)
    return leaked


def screen_directives(
    card: SceneCard,
    canon: Canon,
    personas: list[Persona],
    client: Any,
    judge: GuessJudge,
) -> SceneCard:
    """Rewrite once if the visible lines leak. Then drop plants, then directives."""

    allowed = set(card.must_reveal)

    def leaks(candidate: SceneCard) -> bool:
        return bool(
            leaking_secret_ids(
                visible_lines(candidate), canon, personas, client, judge, allowed=allowed
            )
        )

    if not leaks(card):
        return card
    rewritten = replan_scene(canon, card, client, note="上一版指令让读者猜到了不该猜到的事")
    if not leaks(rewritten):
        return rewritten
    without_plants = rewritten.model_copy(update={"plants": [], "genre_beats": {}})
    if not leaks(without_plants):
        return without_plants
    return without_plants.model_copy(update={"directives": [], "theme_beat": ""})


def visible_lines(card: SceneCard) -> list[str]:
    """Writer-visible lines that describe concrete events and details."""

    beats = [line for lines in card.genre_beats.values() for line in lines]
    return [*card.directives, *card.plants, *card.misdirection, *beats, card.theme_beat]
