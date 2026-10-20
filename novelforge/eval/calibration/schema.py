"""Calibration set: stories split into scenes, secrets with probes, and human answers."""

from __future__ import annotations

from pathlib import Path

import yaml
from pydantic import BaseModel, ConfigDict, Field, model_validator

from novelforge.schema.canon import Canon, Secret
from novelforge.schema.reader import ConfidenceBin, Persona, SkipSpan
from novelforge.schema.scene import LockedScene


class CalibrationSecret(BaseModel):
    """Scoring window is `[ask_from, revealed_in)`.

    `ask_from`: first scene where the probe may be asked. Asking earlier can
    leak by itself (e.g. naming a character before the story introduces them).
    `revealed_in`: scene where the story states the truth.
    """

    model_config = ConfigDict(extra="forbid")

    id: str
    probe_question: str
    truth: str
    answer_keywords: list[str] = Field(default_factory=list)
    ask_from: str | None = None
    revealed_in: str | None = None

    def to_secret(self) -> Secret:
        return Secret(
            id=self.id, title=self.truth, text=self.truth, probe_question=self.probe_question
        )


class CalibrationScene(BaseModel):
    model_config = ConfigDict(extra="forbid")

    scene_id: str
    text: str


class CalibrationStory(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    title: str
    source: str = ""
    renamed: bool = False
    ai_generated: bool = False
    scenes: list[CalibrationScene]
    secrets: list[CalibrationSecret]

    @model_validator(mode="after")
    def _check_ids(self) -> CalibrationStory:
        scene_ids = [scene.scene_id for scene in self.scenes]
        if len(set(scene_ids)) != len(scene_ids):
            raise ValueError("duplicate scene_id")
        for secret in self.secrets:
            for name in ("ask_from", "revealed_in"):
                value = getattr(secret, name)
                if value is not None and value not in scene_ids:
                    raise ValueError(f"{secret.id}.{name} refers to unknown scene")
            if (
                secret.ask_from is not None
                and secret.revealed_in is not None
                and scene_ids.index(secret.ask_from) >= scene_ids.index(secret.revealed_in)
            ):
                raise ValueError(f"{secret.id}.ask_from must come before revealed_in")
        return self

    def canon(self) -> Canon:
        return Canon(title=self.title, secrets=[secret.to_secret() for secret in self.secrets])

    def locked_scenes(self) -> list[LockedScene]:
        return [LockedScene.lock(scene.scene_id, scene.text) for scene in self.scenes]

    def scene_index(self, scene_id: str) -> int:
        return [scene.scene_id for scene in self.scenes].index(scene_id)

    def is_asked(self, scene_id: str, secret: CalibrationSecret) -> bool:
        if secret.ask_from is None:
            return True
        return self.scene_index(scene_id) >= self.scene_index(secret.ask_from)

    def is_scored(self, scene_id: str, secret: CalibrationSecret) -> bool:
        if not self.is_asked(scene_id, secret):
            return False
        if secret.revealed_in is None:
            return True
        return self.scene_index(scene_id) < self.scene_index(secret.revealed_in)

    def keywords(self) -> dict[str, list[str]]:
        return {secret.id: list(secret.answer_keywords) for secret in self.secrets}


class HumanGuess(BaseModel):
    """`correct` may be pre-marked by the annotator; otherwise the judge decides."""

    model_config = ConfigDict(extra="forbid")

    probe_id: str
    question: str = ""
    guess: str = ""
    confidence: ConfidenceBin = "none"
    correct: bool | None = None


class SceneResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    scene_id: str
    guesses: list[HumanGuess] = Field(default_factory=list)
    wants_to_know: list[str] = Field(default_factory=list)
    skip: list[SkipSpan] = Field(default_factory=list)


class HumanResponseSet(BaseModel):
    """One reader's questionnaire for one story, filled scene by scene without going back."""

    model_config = ConfigDict(extra="forbid")

    reader_id: str
    story_id: str
    responses: list[SceneResponse] = Field(default_factory=list)


def _load_yaml(path: Path) -> object:
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def load_story(path: Path) -> CalibrationStory:
    return CalibrationStory.model_validate(_load_yaml(path))


def load_responses(path: Path) -> list[HumanResponseSet]:
    """Load one file, or every *.yaml under a directory."""

    files = sorted(path.glob("*.yaml")) if path.is_dir() else [path]
    return [HumanResponseSet.model_validate(_load_yaml(file)) for file in files]


def load_personas(path: Path) -> list[Persona]:
    data = _load_yaml(path) or {}
    return [Persona.model_validate(item) for item in data.get("personas", [])]  # type: ignore[union-attr]


def blank_questionnaire(story: CalibrationStory, reader_id: str) -> HumanResponseSet:
    return HumanResponseSet(
        reader_id=reader_id,
        story_id=story.id,
        responses=[
            SceneResponse(
                scene_id=scene.scene_id,
                guesses=[
                    HumanGuess(probe_id=secret.id, question=secret.probe_question)
                    for secret in story.secrets
                    if story.is_asked(scene.scene_id, secret)
                ],
            )
            for scene in story.scenes
        ],
    )


def dump_yaml(model: BaseModel) -> str:
    return yaml.safe_dump(model.model_dump(mode="json"), allow_unicode=True, sort_keys=False)
