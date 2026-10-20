import pytest

from novelforge.gates.hooks import check_hooks
from novelforge.gates.pace import check_pace
from novelforge.gates.skim import check_skim
from novelforge.llm.fake import FakeLLMClient
from novelforge.pacing.curve import curve_deviation, tension_curve
from novelforge.pacing.pace import (
    LENGTH_BUDGET,
    PACE_CRAFT,
    REWARD_DIRECTIVE,
    apply_pacing,
    correct_upcoming,
    craft_block,
)
from novelforge.roles.prose import Prose
from novelforge.roles.writer import draft_scene
from novelforge.schema.reader import ReaderReport, SkipSpan
from novelforge.schema.scene import SceneCard
from novelforge.schema.state import BookState
from novelforge.view.filter import SecretLeakError, build_writer_view


def test_apply_pacing_sets_budget_and_is_not_flat() -> None:
    cards = apply_pacing([SceneCard(scene_id=f"sc-{index:02d}") for index in range(1, 9)])
    curve = tension_curve(8)
    assert [card.tension_target for card in cards] == curve
    assert {card.pace for card in cards} >= {"slack", "sprint"}
    for card in cards:
        assert card.length == LENGTH_BUDGET[card.pace]
    assert curve_deviation(curve, [0.5] * 8) > 0.1


def test_low_scenes_force_a_reversal_and_high_scenes_a_reward() -> None:
    card = SceneCard(scene_id="sc-03", pace="steady", length=700, tension_target=0.5)
    reversed_card, kind = correct_upcoming(card, 2, [0.8, 0.8, 0.5], [0.4, 0.4])
    assert kind == "reversal"
    assert reversed_card.pace == "sprint"
    assert reversed_card.tension_target > card.tension_target
    assert REWARD_DIRECTIVE not in reversed_card.directives
    again, _ = correct_upcoming(reversed_card, 2, [0.8, 0.8, 0.5], [0.4, 0.4])
    assert again.directives.count(again.directives[-1]) == 1

    rewarded, reward = correct_upcoming(card, 2, [0.4, 0.4, 0.7], [0.9, 0.9])
    assert reward == "reward"
    assert rewarded.pace == "slack"
    assert rewarded.tension_target < card.tension_target
    assert REWARD_DIRECTIVE in rewarded.directives


def test_writer_prompt_changes_with_pace() -> None:
    client = FakeLLMClient(canned={Prose: Prose(text="他推开门")})
    book = BookState()
    draft_scene(
        build_writer_view(book, SceneCard(scene_id="sc-01", pace="sprint", length=280)),
        client,
    )
    draft_scene(
        build_writer_view(book, SceneCard(scene_id="sc-02", pace="slack", length=900)),
        client,
    )
    sprint = client.calls[0]["messages"][0]["content"]
    slack = client.calls[1]["messages"][0]["content"]
    assert PACE_CRAFT["sprint"] in sprint
    assert PACE_CRAFT["slack"] not in sprint
    assert "280" in sprint
    assert PACE_CRAFT["slack"] in slack
    assert PACE_CRAFT["sprint"] not in slack
    assert craft_block("sprint", 280) != craft_block("slack", 900)


def test_pace_shape_rejects_a_long_sprint_block() -> None:
    assert check_pace("雨" * 40, "sprint").passed is False
    assert check_pace("他推开门\n他关上窗", "sprint").passed is True
    assert check_pace("雨" * 100, "slack").passed is False
    assert check_pace(("雨" * 50) + "\n" + ("雨" * 50), "slack").passed is True


def test_skim_fails_at_fifteen_percent() -> None:
    text = "甲\n乙\n丙\n丁"
    spans = [SkipSpan(scene_id="sc-01", paragraph_start=0, paragraph_end=0)]
    report = ReaderReport(persona_id="p", skip_spans=spans)
    assert check_skim(text, [report], scene_id="sc-01").passed is False
    assert check_skim(text, [ReaderReport(persona_id="p")], scene_id="sc-01").passed is True


def test_hooks_catch_a_missing_ending_and_a_dropped_question() -> None:
    missing = check_hooks("雨一直下", ending_hook="门开了", is_last=False)
    assert missing.passed is False
    assert "门开了" not in " ".join(missing.reasons)
    landed = check_hooks("雨一直下，门开了", ending_hook="门开了", is_last=False)
    assert landed.passed is True
    dropped = check_hooks(
        "雨一直下",
        previous_questions=["灯为什么灭了"],
        wants_to_know=[],
        is_last=True,
    )
    assert dropped.passed is False
    kept = check_hooks(
        "雨一直下",
        previous_questions=["灯为什么灭了"],
        wants_to_know=["灯为什么灭了"],
        is_last=False,
    )
    assert kept.passed is True


def test_hidden_secret_cannot_ride_in_on_a_hook() -> None:
    from novelforge.schema.canon import Canon, Secret

    secret = "账房周先生"
    book = BookState(canon=Canon(secrets=[Secret(id="S-1", title="身份", text=secret)]))
    with pytest.raises(SecretLeakError):
        build_writer_view(book, SceneCard(scene_id="sc-01", ending_hook=secret))
    view = build_writer_view(
        book, SceneCard(scene_id="sc-01", must_reveal=["S-1"], answers_hook=secret)
    )
    assert secret in view.scene.answers_hook
