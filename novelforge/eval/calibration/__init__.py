"""Reader-simulator calibration data. See README.md in this folder."""

from importlib.resources import files
from pathlib import Path

from novelforge.eval.calibration.schema import (
    CalibrationScene,
    CalibrationSecret,
    CalibrationStory,
    HumanGuess,
    HumanResponseSet,
    SceneResponse,
    blank_questionnaire,
    dump_yaml,
    load_personas,
    load_responses,
    load_story,
)


def data_path(name: str) -> Path:
    return Path(str(files(__name__).joinpath(name)))


__all__ = [
    "CalibrationScene",
    "CalibrationSecret",
    "CalibrationStory",
    "HumanGuess",
    "HumanResponseSet",
    "SceneResponse",
    "blank_questionnaire",
    "data_path",
    "dump_yaml",
    "load_personas",
    "load_responses",
    "load_story",
]
