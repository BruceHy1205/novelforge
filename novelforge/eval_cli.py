"""`novelforge eval …` — P1 calibration commands."""

from __future__ import annotations

from enum import StrEnum
from pathlib import Path
from typing import Annotated, Any

import typer

from novelforge.eval.calibration import (
    blank_questionnaire,
    data_path,
    dump_yaml,
    load_personas,
    load_responses,
    load_story,
)
from novelforge.eval.calibration.schema import CalibrationStory

eval_app = typer.Typer(help="Reader-simulator calibration (P1).", no_args_is_help=True)


class JudgeKind(StrEnum):
    llm = "llm"
    keyword = "keyword"


ModelsOption = Annotated[
    Path | None,
    typer.Option("--models", help="models.yaml with per-role routing (default: built-in)."),
]
JudgeOption = Annotated[
    JudgeKind,
    typer.Option("--judge", help="llm: model judges guesses; keyword: answer_keywords only."),
]
FakeOption = Annotated[
    bool,
    typer.Option("--fake", help="Offline dry run: fake model (empty reports) + keyword judge."),
]


def _client(models: Path | None, fake: bool) -> tuple[Any, str]:
    if fake:
        from novelforge.llm.fake import FakeLLMClient

        return FakeLLMClient(), "fake"
    from novelforge.llm.client import LiteLLMClient
    from novelforge.llm.routing import ModelRouting

    routing = ModelRouting.load(models) if models else ModelRouting()
    return LiteLLMClient(routing), routing.model_for("reader_sim")


def _judge(kind: JudgeKind, stories: list[CalibrationStory], client: Any, fake: bool) -> Any:
    from novelforge.roles.guess_judge import KeywordJudge, LLMGuessJudge

    if fake or kind is JudgeKind.keyword:
        keywords: dict[str, list[str]] = {}
        for story in stories:
            keywords.update(story.keywords())
        return KeywordJudge(keywords)
    return LLMGuessJudge(client)


@eval_app.command()
def questionnaire(
    story: Annotated[Path, typer.Argument(help="Calibration story YAML.")],
    reader: Annotated[str, typer.Option("--reader", help="Reader ID, e.g. r01.")],
    out: Annotated[Path | None, typer.Option("--out", help="Write here instead of stdout.")] = None,
) -> None:
    """Generate a blank questionnaire for one reader, pre-filled with scenes and probes."""

    text = dump_yaml(blank_questionnaire(load_story(story), reader))
    if out is None:
        typer.echo(text, nl=False)
        return
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(text, encoding="utf-8")
    typer.echo(f"wrote {out}")


@eval_app.command()
def calibrate(
    stories: Annotated[list[Path], typer.Argument(help="One or more calibration story YAMLs.")],
    responses: Annotated[
        list[Path],
        typer.Option("--responses", help="Questionnaire file or directory (repeatable)."),
    ],
    personas: Annotated[
        Path | None,
        typer.Option("--personas", help="Personas YAML (default: built-in three)."),
    ] = None,
    models: ModelsOption = None,
    judge: JudgeOption = JudgeKind.llm,
    fake: FakeOption = False,
    out: Annotated[Path | None, typer.Option("--out", help="Write the full JSON report.")] = None,
    resamples: Annotated[int, typer.Option(help="Split-half resamples for the ceiling.")] = 200,
    seed: Annotated[int, typer.Option(help="Random seed for split-half resampling.")] = 0,
    workers: Annotated[int, typer.Option(help="Concurrent simulator calls.")] = 4,
    repeats: Annotated[
        int,
        typer.Option(
            help="Independent simulator runs. Exit uses the mean and rejects a crossing range."
        ),
    ] = 1,
) -> None:
    """Run simulated readers over each story and compare them with human questionnaires."""

    from novelforge.eval.calibrate import format_repeated, format_report, run_repeats

    if repeats < 1:
        typer.echo("repeats must be >= 1", err=True)
        raise typer.Exit(code=1)

    loaded = [load_story(path) for path in stories]
    human = [item for path in responses for item in load_responses(path)]
    persona_list = load_personas(personas or data_path("personas.yaml"))
    client, model = _client(models, fake)

    def progress(index: int, total: int) -> None:
        if total > 1:
            typer.echo(f"repeat {index}/{total}", err=True)

    repeated = run_repeats(
        loaded,
        human,
        persona_list,
        client,
        _judge(judge, loaded, client, fake),
        repeats=repeats,
        model=model,
        resamples=resamples,
        seed=seed,
        workers=workers,
        on_repeat=progress,
    )
    text = format_report(repeated.runs[0]) if repeats == 1 else format_repeated(repeated)
    typer.echo(text)
    if out is not None:
        payload = repeated.runs[0] if repeats == 1 else repeated
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(payload.model_dump_json(indent=2), encoding="utf-8")
        typer.echo(f"\nwrote {out}")


@eval_app.command()
def contamination(
    stories: Annotated[list[Path], typer.Argument(help="Calibration story YAMLs.")],
    models: ModelsOption = None,
    judge: JudgeOption = JudgeKind.llm,
    fake: FakeOption = False,
) -> None:
    """Ask the model each probe without the text; correct answers mean the story is contaminated."""

    from novelforge.eval.contamination import check_contamination

    loaded = [load_story(path) for path in stories]
    client, _model = _client(models, fake)
    judge_impl = _judge(judge, loaded, client, fake)
    dirty = False
    for story in loaded:
        for result in check_contamination(story, client, judge_impl):
            flag = "CONTAMINATED" if result.contaminated else "clean"
            dirty = dirty or result.contaminated
            typer.echo(f"{story.id}/{result.secret_id}: {flag}  answer={result.answer!r}")
    if dirty:
        typer.echo("\nRename, rewrite, or drop contaminated stories before calibrating.")
        raise typer.Exit(code=1)
