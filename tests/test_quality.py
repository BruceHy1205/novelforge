"""P4: behavior directives, clue budget, G2/G4/G5/G7, and pinpoint revision."""

from __future__ import annotations

from typing import Any

import pytest
from pydantic import BaseModel

from novelforge.gates.behavior import check_directives
from novelforge.gates.hint import check_hint
from novelforge.gates.inference import check_inference
from novelforge.gates.pov import check_pov
from novelforge.gates.style import DEFAULT_BANNED, check_style
from novelforge.llm.fake import FakeLLMClient
from novelforge.pipeline import run_scene
from novelforge.roles.behavior import apply_behavior, behavior_lines
from novelforge.roles.clues import build_clues
from novelforge.roles.guess_judge import KeywordJudge
from novelforge.roles.prose import ParagraphFix, ParagraphFixes, Prose
from novelforge.roles.reviser import revise_scene
from novelforge.schema.canon import Canon, RevealPlanItem, Secret
from novelforge.schema.clues import Clue
from novelforge.schema.reader import Persona, POVState, ReaderReport
from novelforge.schema.scene import PublicSceneCard, SceneCard, WriterView
from novelforge.schema.state import BookState
from novelforge.view.filter import SecretLeakError, build_writer_view

CANON = Canon(
    secrets=[Secret(id="S-1", title="身份", text="账房周先生", probe_question="谁最不对劲？")],
    reveal_plan=[RevealPlanItem(secret_id="S-1", earliest_scene_id="sc-02", method="withhold")],
)
IDS = ["sc-01", "sc-02", "sc-03"]


def test_behavior_lines_drop_the_cause() -> None:
    assert behavior_lines(["他放下杯子，因为有人在看。"]) == ["他放下杯子"]
    assert behavior_lines(["因为有人在看"]) == []
    card = apply_behavior(
        SceneCard(scene_id="sc-02", directives=[]),
        Canon(
            secrets=[Secret(id="S-1", title="t", text="秘密", probe_question="谁？")],
            reveal_plan=[RevealPlanItem(secret_id="S-1", earliest_scene_id="sc-02", method="hint")],
        ),
    )
    assert card.directives == ["安排一个看得见的异常，不要解释。"]


def test_clue_budget_stops_a_withheld_secret_after_one_trace() -> None:
    cards = [
        SceneCard(scene_id="sc-01", must_withhold=["S-1"], directives=["他擦了杯子。"]),
        SceneCard(scene_id="sc-02", must_withhold=["S-1"], directives=["灯灭了。"]),
    ]
    clues = build_clues(cards, CANON)
    assert [clue.planted_in for clue in clues] == ["sc-01"]
    assert clues[0].strength == "trace"
    assert clues[0].visibility == "public"


def test_inference_cap_follows_public_clues_and_ignores_author_only() -> None:
    public = [
        Clue(
            id="c",
            text="他擦了杯子",
            secret_id="S-1",
            planted_in="sc-01",
            strength="pointer",
        )
    ]
    hint_plan = Canon(
        secrets=CANON.secrets,
        reveal_plan=[RevealPlanItem(secret_id="S-1", earliest_scene_id="sc-03", method="hint")],
    )
    ahead = check_inference({"p": {"S-1": "suspect"}}, hint_plan, "sc-03", IDS, public)
    assert ahead.passed is False
    hidden = [public[0].model_copy(update={"visibility": "author_only"})]
    allowed = check_inference({"p": {"S-1": "hint"}}, hint_plan, "sc-03", IDS, hidden)
    assert allowed.passed is True
    reveal = Canon(
        secrets=CANON.secrets,
        reveal_plan=[RevealPlanItem(secret_id="S-1", earliest_scene_id="sc-01", method="reveal")],
    )
    certain = check_inference({"p": {"S-1": "certain"}}, reveal, "sc-01", IDS, public)
    assert certain.passed is True


def test_hint_full_version_catches_overshoot_carry_and_a_missing_clue() -> None:
    hint = Canon(
        secrets=CANON.secrets,
        reveal_plan=[RevealPlanItem(secret_id="S-1", earliest_scene_id="sc-02", method="hint")],
    )
    over = check_hint({"p": {"S-1": "certain"}}, hint, "sc-02", IDS)
    assert over.passed is False
    assert "hint beat became certain" in over.reasons
    carried = check_hint({"p": {"S-1": "none"}}, hint, "sc-03", IDS)
    assert "hint did not carry" in carried.reasons
    loud = check_hint({"p": {"S-1": "suspect"}}, hint, "sc-02", IDS, hint_budget="light")
    assert loud.passed is False
    quiet = check_hint({"p": {"S-1": "hint"}}, hint, "sc-02", IDS, hint_budget="heavy")
    assert quiet.passed is False
    unplanted = check_hint({"p": {"S-1": "hint"}}, hint, "sc-02", IDS, clues=[])
    assert unplanted.passed is False
    assert "hint beat has no clue" in unplanted.reasons


def test_pov_blocks_another_mind_and_a_hidden_fact() -> None:
    secret = "账房周先生"
    pov = POVState(character_id="guest", blocked_secret_ids=["S-1"])
    secrets = [Secret(id="S-1", title="身份", text=secret)]
    blocked = check_pov(f"门口站着{secret}", pov, secrets=secrets)
    assert blocked.passed is False
    assert secret not in " ".join(blocked.reasons)
    other = POVState(character_id="keeper", name="林伯")
    hopped = check_pov("林伯知道门没有锁。", POVState(character_id="guest"), others=[other])
    assert hopped.passed is False
    assert check_pov("雨一直下。", None).passed is True


def test_style_rejects_a_banned_phrase_and_a_copied_sample() -> None:
    assert check_style("他不禁回头").passed is False
    assert "不禁" in DEFAULT_BANNED
    sample = "他说话很短，天气就是心情。"
    copied = check_style(f"开场。{sample}", banned=[], samples=[sample])
    assert copied.passed is False
    assert check_style("他回头。", banned=[]).passed is True


def test_banned_pattern_cannot_smuggle_a_secret() -> None:
    secret = "账房周先生"
    book = BookState(
        canon=Canon(secrets=[Secret(id="S-1", title="身份", text=secret)]),
        banned_patterns=[secret],
    )
    with pytest.raises(SecretLeakError):
        build_writer_view(book, SceneCard(scene_id="sc-01"))


def test_pinpoint_revision_leaves_the_clean_paragraph() -> None:
    def respond(messages: list[dict[str, str]], model: type[BaseModel]) -> BaseModel | None:
        name = model.__name__
        if name == "ParagraphFixes":
            return ParagraphFixes(fixes=[ParagraphFix(index=1, text="他回头")])
        if name == "Prose":
            return Prose(text="门开了\n他不禁回头")
        if name == "ReaderReport":
            return ReaderReport(persona_id="p", tension="high")
        return None

    result = run_scene(
        BookState(canon=CANON),
        SceneCard(scene_id="sc-01", length=8, tension_target=0.3, pace="steady"),
        ["sc-01"],
        FakeLLMClient(responder=respond),
        _judge(),
        [Persona(id="p", name="普通读者")],
    )
    assert result["status"] == "locked"
    assert result["locked"].text == "门开了\n他回头"
    assert result["book"].gate_failures.get("style", 0) >= 1


def test_revise_scene_splices_only_the_requested_paragraph() -> None:
    view = WriterView(scene=PublicSceneCard(scene_id="sc-01", pace="steady", length=8))

    def respond(_messages: list[dict[str, str]], model: type[BaseModel]) -> BaseModel | None:
        if model.__name__ == "ParagraphFixes":
            return ParagraphFixes(
                fixes=[
                    ParagraphFix(index=0, text="不该改"),
                    ParagraphFix(index=1, text="他回头"),
                ]
            )
        return None

    text = revise_scene(
        view,
        "门开了\n他不禁回头",
        ["banned phrase: 不禁"],
        FakeLLMClient(responder=respond),
        only_paragraphs=[1],
    )
    assert text == "门开了\n他回头"


def test_directive_gate_rejects_a_cause_without_calling_the_reader() -> None:
    card = SceneCard(scene_id="sc-01", directives=["他离开，因为账房在看"])
    result = check_directives(card, CANON, [], FakeLLMClient(), _judge())
    assert result.passed is False
    assert result.reasons == ["directive states a cause"]


def _judge() -> Any:
    return KeywordJudge({"S-1": ["账房周先生"]})
