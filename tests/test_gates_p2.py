from novelforge.gates.hint import check_hint
from novelforge.gates.inference import check_inference, check_reveal_authority
from novelforge.gates.length import check_length, text_length
from novelforge.gates.literal import check_literal
from novelforge.gates.tension import check_tension
from novelforge.schema.canon import Canon, RevealPlanItem, Secret
from novelforge.schema.reader import ReaderReport

CANON = Canon(
    secrets=[Secret(id="S-1", title="t", text="账房周先生当晚去过灯塔", probe_question="谁？")],
    reveal_plan=[RevealPlanItem(secret_id="S-1", earliest_scene_id="sc-03", method="hint")],
)


def test_near_match_catches_a_comma_split_secret() -> None:
    secret = "账房周先生当晚去过灯塔"
    result = check_literal(f"有人说{secret[:5]}，{secret[5:]}", [secret])
    assert result.passed is False
    assert "near-match leak" in result.reasons
    assert secret not in " ".join(result.reasons)


def test_short_secret_is_not_a_near_match() -> None:
    assert check_literal("周先生站在门口", ["周"]).passed is True


def test_chinese_length_counts_characters() -> None:
    assert text_length("雨一直下") == 4
    assert check_length("雨一直下", target_words=4, tolerance=0.1).passed is True


def test_inference_fails_when_the_reader_is_ahead_of_the_plan() -> None:
    early = check_inference({"p": {"S-1": "suspect"}}, CANON, "sc-01", ["sc-01", "sc-02", "sc-03"])
    on_beat = check_inference({"p": {"S-1": "hint"}}, CANON, "sc-03", ["sc-01", "sc-02", "sc-03"])
    assert early.passed is False
    assert on_beat.passed is True


def test_inference_tolerance_allows_one_step_but_never_certainty() -> None:
    ids = ["sc-01", "sc-02", "sc-03"]
    one_step = check_inference({"p": {"S-1": "suspect"}}, CANON, "sc-03", ids, tolerance=1)
    two_steps = check_inference({"p": {"S-1": "suspect"}}, CANON, "sc-01", ids, tolerance=1)
    certain = check_inference({"p": {"S-1": "certain"}}, CANON, "sc-03", ids, tolerance=2)
    assert one_step.passed is True
    assert one_step.details["ahead"] == "1"
    assert two_steps.passed is False
    assert certain.passed is False


def test_reveal_authority_blocks_certainty_before_a_reveal() -> None:
    result = check_reveal_authority({"p": {"S-1": "certain"}}, CANON, "sc-03", ["sc-03"])
    assert result.passed is False


def test_hint_beat_fails_when_nobody_notices() -> None:
    missed = check_hint({"p": {"S-1": "none"}}, CANON, "sc-03", ["sc-01", "sc-02", "sc-03"])
    landed = check_hint({"p": {"S-1": "hint"}}, CANON, "sc-03", ["sc-01", "sc-02", "sc-03"])
    assert missed.passed is False
    assert landed.passed is True


def test_tension_below_target_fails() -> None:
    flat = check_tension([ReaderReport(persona_id="p", tension="flat")], target=0.8)
    high = check_tension([ReaderReport(persona_id="p", tension="high")], target=0.8)
    assert flat.passed is False
    assert high.passed is True
