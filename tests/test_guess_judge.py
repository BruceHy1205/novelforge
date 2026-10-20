from __future__ import annotations

from novelforge.llm.fake import FakeLLMClient
from novelforge.roles.guess_judge import (
    GuessVerdict,
    KeywordJudge,
    LLMGuessJudge,
    effective_confidence,
    update_reader_state,
)
from novelforge.schema.reader import ReaderGuess, ReaderReport, ReaderState


def test_keyword_judge() -> None:
    judge = KeywordJudge({"S-1": ["周", "灯塔"]})
    assert judge.judge("S-1", "q", "t", "周先生去过灯塔").match == "correct"
    assert judge.judge("S-1", "q", "t", "周先生").match == "partial"
    assert judge.judge("S-1", "q", "t", "老板娘").match == "wrong"
    assert judge.judge("S-1", "q", "t", "不知道").match == "wrong"


def test_effective_confidence() -> None:
    assert effective_confidence(GuessVerdict(match="correct"), "certain") == "certain"
    assert effective_confidence(GuessVerdict(match="partial"), "certain") == "hint"
    assert effective_confidence(GuessVerdict(match="partial"), "none") == "none"
    assert effective_confidence(GuessVerdict(match="wrong"), "certain") == "none"


def test_llm_judge_skips_empty_guesses_and_sees_truth() -> None:
    client = FakeLLMClient(canned={GuessVerdict: GuessVerdict(match="correct")})
    judge = LLMGuessJudge(client)

    assert judge.judge("S-1", "谁？", "周先生", "").match == "wrong"
    assert client.calls == []

    assert judge.judge("S-1", "谁？", "周先生", "账房").match == "correct"
    prompt = client.calls[0]["messages"][0]["content"]
    assert "周先生" in prompt and "账房" in prompt
    assert client.calls[0]["role"] == "gate"


def test_update_reader_state() -> None:
    state = ReaderState(persona_id="p", secret_confidence={"S-2": "hint"})
    report = ReaderReport(
        persona_id="p",
        last_scene_id="sc-03",
        guesses=[
            ReaderGuess(probe_id="S-1", guess="周", confidence="certain"),
            ReaderGuess(probe_id="S-2", guess="仇人", confidence="suspect"),
        ],
        wants_to_know=["动机"],
    )
    verdicts = {"S-1": GuessVerdict(match="correct"), "S-2": GuessVerdict(match="wrong")}
    updated = update_reader_state(state, report, verdicts)
    assert updated.secret_confidence == {"S-1": "certain", "S-2": "none"}
    assert updated.open_questions == ["动机"]
    assert updated.last_scene_id == "sc-03"
