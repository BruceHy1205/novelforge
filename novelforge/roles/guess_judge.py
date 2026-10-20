"""Canon-side judge: does a reader's free-text guess match the hidden truth?

The reader simulator is blind to Canon, so it reports guesses, not per-secret
confidence. This module is the only place guesses meet the truth. The same
judge scores human questionnaire answers, so simulator and humans are
measured on one scale.
"""

from __future__ import annotations

from typing import Any, Literal, Protocol

from pydantic import BaseModel, ConfigDict

from novelforge.genres import Genre, fill, resolve
from novelforge.schema.reader import CONFIDENCE_ORDER, ConfidenceBin, ReaderReport, ReaderState

Match = Literal["wrong", "partial", "correct"]

NO_GUESS = {"", "不知道", "没头绪", "无", "unknown", "?", "？"}

JUDGE_TEMPLATE = """你是<<identity>>。比较读者的猜测和真相，判断读者是否猜中。

- correct：猜测抓住了真相的核心（例如<<examples>>），细节可以不全
- partial：方向对了一部分（例如锁定了范围但没锁定人，或说对了人但理由完全错）
- wrong：没有猜中，或猜测含糊到无法判断

问题：{question}
真相：{truth}
读者猜测：{guess}"""


class GuessVerdict(BaseModel):
    model_config = ConfigDict(extra="forbid")

    match: Match = "wrong"
    rationale: str = ""


class GuessJudge(Protocol):
    def judge(self, secret_id: str, question: str, truth: str, guess: str) -> GuessVerdict: ...


def is_no_guess(guess: str) -> bool:
    return guess.strip().lower() in NO_GUESS


class KeywordJudge:
    """Offline judge: all keywords present → correct, some → partial, none → wrong."""

    def __init__(self, keywords: dict[str, list[str]]) -> None:
        self.keywords = keywords

    def judge(self, secret_id: str, question: str, truth: str, guess: str) -> GuessVerdict:
        words = [word for word in self.keywords.get(secret_id, []) if word]
        if is_no_guess(guess) or not words:
            return GuessVerdict(match="wrong")
        hits = sum(1 for word in words if word in guess)
        if hits == len(words):
            return GuessVerdict(match="correct")
        if hits:
            return GuessVerdict(match="partial")
        return GuessVerdict(match="wrong")


class LLMGuessJudge:
    def __init__(self, client: Any, genre: Genre | None = None) -> None:
        self.client = client
        self.genre = genre

    def judge(self, secret_id: str, question: str, truth: str, guess: str) -> GuessVerdict:
        if is_no_guess(guess):
            return GuessVerdict(match="wrong")
        template = fill(JUDGE_TEMPLATE, resolve(self.genre), "judge")
        prompt = template.format(question=question, truth=truth, guess=guess)
        return self.client.complete(
            messages=[{"role": "user", "content": prompt}],
            response_model=GuessVerdict,
            role="gate",
        )


def effective_confidence(verdict: GuessVerdict, confidence: ConfidenceBin) -> ConfidenceBin:
    """How close the reader is to the truth: wrong counts as `none`, partial caps at `hint`."""

    if verdict.match == "correct":
        return confidence
    if verdict.match == "partial":
        return min(confidence, "hint", key=CONFIDENCE_ORDER.index)
    return "none"


def update_reader_state(
    state: ReaderState,
    report: ReaderReport,
    verdicts: dict[str, GuessVerdict],
) -> ReaderState:
    confidence = dict(state.secret_confidence)
    for guess in report.guesses:
        verdict = verdicts.get(guess.probe_id)
        if verdict is not None:
            confidence[guess.probe_id] = effective_confidence(verdict, guess.confidence)
    return state.model_copy(
        update={
            "last_scene_id": report.last_scene_id or state.last_scene_id,
            "secret_confidence": confidence,
            "open_questions": list(report.wants_to_know),
        }
    )
