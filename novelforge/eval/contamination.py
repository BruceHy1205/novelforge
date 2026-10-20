"""Training-data contamination check for calibration stories.

Ask the model each probe question with only the title and source — no text.
If it answers correctly, it has likely seen the story, and its "guesses"
during calibration would be recall rather than inference. Such stories must
be renamed/rewritten or dropped.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict

from novelforge.eval.calibration.schema import CalibrationStory
from novelforge.roles.guess_judge import GuessJudge, GuessVerdict

CONTAMINATION_PROMPT = """下面是一部小说的标题和出处，以及一个关于它的问题。
如果你读过或了解这部作品，请直接回答；
如果不了解，answer 写“不知道”，knows_story 填 false。不要编造。

作品：{title}
出处：{source}
问题：{question}"""


class ContaminationAnswer(BaseModel):
    model_config = ConfigDict(extra="forbid")

    knows_story: bool = False
    answer: str = ""


class ContaminationResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    secret_id: str
    knows_story: bool
    answer: str
    verdict: GuessVerdict

    @property
    def contaminated(self) -> bool:
        return self.verdict.match != "wrong"


def check_contamination(
    story: CalibrationStory,
    client: Any,
    judge: GuessJudge,
) -> list[ContaminationResult]:
    results: list[ContaminationResult] = []
    for secret in story.secrets:
        prompt = CONTAMINATION_PROMPT.format(
            title=story.title,
            source=story.source or "未知",
            question=secret.probe_question,
        )
        answer = client.complete(
            messages=[{"role": "user", "content": prompt}],
            response_model=ContaminationAnswer,
            role="reader_sim",
        )
        verdict = judge.judge(secret.id, secret.probe_question, secret.truth, answer.answer)
        results.append(
            ContaminationResult(
                secret_id=secret.id,
                knows_story=answer.knows_story,
                answer=answer.answer,
                verdict=verdict,
            )
        )
    return results
