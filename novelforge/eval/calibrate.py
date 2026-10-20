"""P1 calibration: compare simulated readers with human readers, scene by scene.

Every (scene, secret) pair before the story reveals that secret is one cell.
Each reader — simulated or human — gets an *effective* confidence per cell:
their stated confidence if the judge says their guess is right, capped at
`hint` if partly right, `none` if wrong. Metrics are computed on those cells.
"""

from __future__ import annotations

import math
import random
import threading
from collections.abc import Iterable
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from statistics import mean
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from novelforge.eval.calibration.schema import CalibrationStory, HumanResponseSet
from novelforge.eval.metrics import confidence_index, jaccard, spearman
from novelforge.roles.guess_judge import GuessJudge, GuessVerdict, effective_confidence
from novelforge.roles.reader_sim import PROMPT_VERSION, probes_from_canon, simulate_reader
from novelforge.schema.reader import ConfidenceBin, Persona, ReaderReport

SPEARMAN_FLOOR = 0.6
CEILING_SHARE = 0.8
MAX_MISS_RATE = 0.2
MAX_FALSE_ALARM_RATE = 0.2
SUSPECT = confidence_index("suspect")
CERTAIN = confidence_index("certain")

Grid = dict[str, dict[str, ConfidenceBin]]
Skips = dict[str, set[int]]


class CachedJudge:
    """Memoize verdicts so repeated guesses cost one judge call."""

    def __init__(self, inner: GuessJudge) -> None:
        self.inner = inner
        self._cache: dict[tuple[str, str], GuessVerdict] = {}
        self._lock = threading.Lock()

    def judge(self, secret_id: str, question: str, truth: str, guess: str) -> GuessVerdict:
        key = (secret_id, guess.strip())
        with self._lock:
            cached = self._cache.get(key)
        if cached is not None:
            return cached
        verdict = self.inner.judge(secret_id, question, truth, guess)
        with self._lock:
            self._cache[key] = verdict
        return verdict


@dataclass
class StoryRun:
    story: CalibrationStory
    sim: dict[str, Grid] = field(default_factory=dict)
    sim_skips: dict[str, Skips] = field(default_factory=dict)
    human: dict[str, Grid] = field(default_factory=dict)
    human_skips: dict[str, Skips] = field(default_factory=dict)
    reports: dict[str, list[ReaderReport]] = field(default_factory=dict)


def simulate_story(
    run: StoryRun,
    personas: list[Persona],
    client: Any,
    judge: GuessJudge,
    *,
    workers: int = 4,
) -> None:
    """Every (persona, scene) call is independent, so they run concurrently."""

    story = run.story
    all_probes = probes_from_canon(story.canon())
    secrets = {secret.id: secret for secret in story.secrets}
    locked = story.locked_scenes()

    def one(persona: Persona, index: int) -> tuple[ReaderReport, dict[str, ConfidenceBin]]:
        scene_id = locked[index].scene_id
        probes = [p for p in all_probes if story.is_asked(scene_id, secrets[p.probe_id])]
        report = simulate_reader(locked[: index + 1], persona, probes, client=client)
        row: dict[str, ConfidenceBin] = {}
        for guess in report.guesses:
            secret = secrets[guess.probe_id]
            verdict = judge.judge(secret.id, secret.probe_question, secret.truth, guess.guess)
            row[secret.id] = effective_confidence(verdict, guess.confidence)
        return report, row

    jobs = [(persona, index) for persona in personas for index in range(len(locked))]
    with ThreadPoolExecutor(max_workers=max(1, workers)) as pool:
        results = list(pool.map(lambda job: one(*job), jobs))

    for (persona, index), (report, row) in zip(jobs, results, strict=True):
        scene_id = locked[index].scene_id
        run.sim.setdefault(persona.id, {})[scene_id] = row
        run.sim_skips.setdefault(persona.id, {})[scene_id] = set().union(
            *(span.paragraphs() for span in report.skip_spans)
        )
        run.reports.setdefault(persona.id, []).append(report)


def score_humans(run: StoryRun, responses: Iterable[HumanResponseSet], judge: GuessJudge) -> None:
    secrets = {secret.id: secret for secret in run.story.secrets}
    for response_set in responses:
        if response_set.story_id != run.story.id:
            continue
        grid: Grid = {}
        skips: Skips = {}
        for scene in response_set.responses:
            row: dict[str, ConfidenceBin] = {secret_id: "none" for secret_id in secrets}
            for guess in scene.guesses:
                secret = secrets.get(guess.probe_id)
                if secret is None:
                    continue
                if guess.correct is not None:
                    verdict = GuessVerdict(match="correct" if guess.correct else "wrong")
                else:
                    verdict = judge.judge(
                        secret.id, secret.probe_question, secret.truth, guess.guess
                    )
                row[secret.id] = effective_confidence(verdict, guess.confidence)
            grid[scene.scene_id] = row
            skips[scene.scene_id] = set().union(*(s.paragraphs() for s in scene.skip))
        run.human[response_set.reader_id] = grid
        run.human_skips[response_set.reader_id] = skips


class SecretTiming(BaseModel):
    """When humans (majority ≥ suspect) and any simulated persona (≥ suspect) first caught on."""

    model_config = ConfigDict(extra="forbid")

    story_id: str
    secret_id: str
    human_scene: str | None
    sim_scene: str | None
    offset: int | None = Field(description="sim scene index minus human scene index")
    missed: bool | None


class ExitCheck(BaseModel):
    model_config = ConfigDict(extra="forbid")

    spearman_target: float
    spearman_ok: bool
    miss_ok: bool
    false_alarm_ok: bool
    passed: bool
    notes: list[str] = Field(default_factory=list)


class CalibrationMetrics(BaseModel):
    model_config = ConfigDict(extra="forbid")

    n_cells: int
    n_readers: int
    spearman_by_persona: dict[str, float | None]
    spearman_ensemble: float | None
    human_ceiling: float | None
    miss_rate: float | None
    false_alarm_rate: float | None
    false_alarm_cells: int
    skip_overlap_by_persona: dict[str, float | None]
    timings: list[SecretTiming]
    exit: ExitCheck


class CalibrationReport(BaseModel):
    model_config = ConfigDict(extra="forbid")

    prompt_version: str = PROMPT_VERSION
    model: str = ""
    personas: list[str]
    stories: list[str]
    pooled: CalibrationMetrics
    per_story: dict[str, CalibrationMetrics]
    sim_reports: dict[str, dict[str, list[ReaderReport]]]


@dataclass(frozen=True)
class _Cell:
    run: StoryRun
    scene_id: str
    secret_id: str


def _cells(runs: list[StoryRun]) -> list[_Cell]:
    cells: list[_Cell] = []
    for run in runs:
        for scene in run.story.scenes:
            if not any(scene.scene_id in grid for grid in run.human.values()):
                continue
            for secret in run.story.secrets:
                if run.story.is_scored(scene.scene_id, secret):
                    cells.append(_Cell(run, scene.scene_id, secret.id))
    return cells


def _human_values(cell: _Cell, readers: Iterable[str] | None = None) -> list[int]:
    ids = readers if readers is not None else cell.run.human.keys()
    return [
        confidence_index(cell.run.human[reader][cell.scene_id][cell.secret_id])
        for reader in ids
        if cell.scene_id in cell.run.human[reader]
    ]


def _sim_value(cell: _Cell, persona_id: str) -> int:
    row = cell.run.sim.get(persona_id, {}).get(cell.scene_id, {})
    return confidence_index(row.get(cell.secret_id, "none"))


def _correlations(cells: list[_Cell], persona_ids: list[str]) -> tuple[dict, float | None]:
    human = [mean(_human_values(cell)) for cell in cells]
    by_persona = {pid: spearman([_sim_value(c, pid) for c in cells], human) for pid in persona_ids}
    ensemble = None
    if persona_ids:
        sim = [mean(_sim_value(cell, pid) for pid in persona_ids) for cell in cells]
        ensemble = spearman(sim, human)
    return by_persona, ensemble


def _ceiling(cells: list[_Cell], resamples: int, seed: int) -> float | None:
    rng = random.Random(seed)
    eligible = [cell for cell in cells if len(cell.run.human) >= 2]
    if not eligible:
        return None
    runs = {id(cell.run): cell.run for cell in eligible}
    values: list[float] = []
    for _ in range(resamples):
        halves: dict[int, tuple[list[str], list[str]]] = {}
        for key, run in runs.items():
            readers = sorted(run.human)
            rng.shuffle(readers)
            cut = len(readers) // 2
            halves[key] = (readers[:cut], readers[cut:])
        left: list[float] = []
        right: list[float] = []
        for cell in eligible:
            first, second = halves[id(cell.run)]
            a, b = _human_values(cell, first), _human_values(cell, second)
            if a and b:
                left.append(mean(a))
                right.append(mean(b))
        rho = spearman(left, right)
        if rho is not None:
            values.append(rho)
    return mean(values) if values else None


def _majority(values: list[int], predicate: Any) -> bool:
    return bool(values) and sum(1 for v in values if predicate(v)) / len(values) > 0.5


def _timings(runs: list[StoryRun], persona_ids: list[str]) -> list[SecretTiming]:
    timings: list[SecretTiming] = []
    for run in runs:
        story = run.story
        for secret in story.secrets:
            scored = [s.scene_id for s in story.scenes if story.is_scored(s.scene_id, secret)]
            human_scene = next(
                (
                    sid
                    for sid in scored
                    if _majority(_human_values(_Cell(run, sid, secret.id)), lambda v: v >= SUSPECT)
                ),
                None,
            )
            sim_scene = next(
                (
                    sid
                    for sid in scored
                    if any(
                        _sim_value(_Cell(run, sid, secret.id), p) >= SUSPECT for p in persona_ids
                    )
                ),
                None,
            )
            offset = missed = None
            if human_scene is not None:
                human_index = story.scene_index(human_scene)
                if sim_scene is None:
                    missed = True
                else:
                    offset = story.scene_index(sim_scene) - human_index
                    missed = offset > 0
            timings.append(
                SecretTiming(
                    story_id=story.id,
                    secret_id=secret.id,
                    human_scene=human_scene,
                    sim_scene=sim_scene,
                    offset=offset,
                    missed=missed,
                )
            )
    return timings


def _false_alarms(cells: list[_Cell], persona_ids: list[str]) -> tuple[float | None, int]:
    quiet = [cell for cell in cells if _majority(_human_values(cell), lambda v: v == 0)]
    alarms = [
        cell for cell in quiet if any(_sim_value(cell, pid) >= CERTAIN for pid in persona_ids)
    ]
    rate = len(alarms) / len(quiet) if quiet else None
    return rate, len(alarms)


def _skip_overlap(runs: list[StoryRun], persona_ids: list[str]) -> dict[str, float | None]:
    out: dict[str, float | None] = {}
    for pid in persona_ids:
        scores: list[float] = []
        for run in runs:
            for scene in run.story.scenes:
                marks = [
                    skips[scene.scene_id]
                    for skips in run.human_skips.values()
                    if scene.scene_id in skips
                ]
                if not marks:
                    continue
                need = math.ceil(len(marks) / 2)
                counted = set().union(*marks)
                human_set = {p for p in counted if sum(p in m for m in marks) >= need}
                sim_set = run.sim_skips.get(pid, {}).get(scene.scene_id, set())
                score = jaccard(human_set, sim_set)
                if score is not None:
                    scores.append(score)
        out[pid] = mean(scores) if scores else None
    return out


def _exit_check(
    ensemble: float | None,
    ceiling: float | None,
    miss_rate: float | None,
    false_alarm_rate: float | None,
) -> ExitCheck:
    notes: list[str] = []
    if ceiling is None:
        target = SPEARMAN_FLOOR
        notes.append("human ceiling unavailable (need ≥ 2 readers per story)")
    elif ceiling < SPEARMAN_FLOOR:
        target = CEILING_SHARE * ceiling
        notes.append(f"human ceiling {ceiling:.2f} < {SPEARMAN_FLOOR}; target is 80% of ceiling")
    else:
        target = max(SPEARMAN_FLOOR, CEILING_SHARE * ceiling)
    spearman_ok = ensemble is not None and ensemble >= target
    if ensemble is None:
        notes.append("simulator correlation undefined (constant series or too few cells)")
    miss_ok = miss_rate is not None and miss_rate < MAX_MISS_RATE
    if miss_rate is None:
        notes.append("no secret was caught by a human majority; miss rate undefined")
    false_alarm_ok = false_alarm_rate is not None and false_alarm_rate < MAX_FALSE_ALARM_RATE
    if false_alarm_rate is None:
        notes.append("no cell where a human majority had no idea; false-alarm rate undefined")
    return ExitCheck(
        spearman_target=round(target, 4),
        spearman_ok=spearman_ok,
        miss_ok=miss_ok,
        false_alarm_ok=false_alarm_ok,
        passed=spearman_ok and miss_ok and false_alarm_ok,
        notes=notes,
    )


def compute_metrics(
    runs: list[StoryRun],
    persona_ids: list[str],
    *,
    resamples: int = 200,
    seed: int = 0,
) -> CalibrationMetrics:
    cells = _cells(runs)
    by_persona, ensemble = _correlations(cells, persona_ids) if cells else ({}, None)
    ceiling = _ceiling(cells, resamples, seed)
    timings = _timings(runs, persona_ids)
    judged = [t for t in timings if t.missed is not None]
    miss_rate = sum(t.missed for t in judged) / len(judged) if judged else None
    false_alarm_rate, false_alarm_cells = _false_alarms(cells, persona_ids)
    return CalibrationMetrics(
        n_cells=len(cells),
        n_readers=sum(len(run.human) for run in runs),
        spearman_by_persona=by_persona,
        spearman_ensemble=ensemble,
        human_ceiling=ceiling,
        miss_rate=miss_rate,
        false_alarm_rate=false_alarm_rate,
        false_alarm_cells=false_alarm_cells,
        skip_overlap_by_persona=_skip_overlap(runs, persona_ids),
        timings=timings,
        exit=_exit_check(ensemble, ceiling, miss_rate, false_alarm_rate),
    )


def _cached(judge: GuessJudge) -> CachedJudge:
    return judge if isinstance(judge, CachedJudge) else CachedJudge(judge)


def run_calibration(
    stories: list[CalibrationStory],
    responses: list[HumanResponseSet],
    personas: list[Persona],
    client: Any,
    judge: GuessJudge,
    *,
    model: str = "",
    resamples: int = 200,
    seed: int = 0,
    workers: int = 4,
) -> CalibrationReport:
    cached = _cached(judge)
    runs: list[StoryRun] = []
    for story in stories:
        run = StoryRun(story=story)
        score_humans(run, responses, cached)
        simulate_story(run, personas, client, cached, workers=workers)
        runs.append(run)
    persona_ids = [persona.id for persona in personas]
    return CalibrationReport(
        model=model,
        personas=persona_ids,
        stories=[story.id for story in stories],
        pooled=compute_metrics(runs, persona_ids, resamples=resamples, seed=seed),
        per_story={
            run.story.id: compute_metrics([run], persona_ids, resamples=resamples, seed=seed)
            for run in runs
        },
        sim_reports={run.story.id: run.reports for run in runs},
    )


class Spread(BaseModel):
    """Mean and range of one metric across repeats. `mean` is null if any repeat is undefined."""

    model_config = ConfigDict(extra="forbid")

    mean: float | None
    low: float | None
    high: float | None
    values: list[float | None]


class TimingSpread(BaseModel):
    model_config = ConfigDict(extra="forbid")

    story_id: str
    secret_id: str
    human_scene: str | None
    sim_scenes: list[str | None]
    stable: bool


class RepeatedCalibrationReport(BaseModel):
    model_config = ConfigDict(extra="forbid")

    repeats: int
    prompt_version: str = PROMPT_VERSION
    model: str = ""
    personas: list[str]
    stories: list[str]
    n_cells: int
    n_readers: int
    human_ceiling: float | None
    spearman_ensemble: Spread
    spearman_by_persona: dict[str, Spread]
    miss_rate: Spread
    false_alarm_rate: Spread
    skip_overlap_by_persona: dict[str, Spread]
    timings: list[TimingSpread]
    exit: ExitCheck
    runs: list[CalibrationReport]


def _spread(values: list[float | None]) -> Spread:
    present = [value for value in values if value is not None]
    complete = bool(values) and len(present) == len(values)
    return Spread(
        mean=mean(present) if complete else None,
        low=min(present) if present else None,
        high=max(present) if present else None,
        values=list(values),
    )


def aggregate_reports(reports: list[CalibrationReport]) -> RepeatedCalibrationReport:
    """Exit criteria use the mean, and also fail when any repeat crosses a threshold."""

    if not reports:
        raise ValueError("no reports to aggregate")
    first = reports[0]
    pooled = [report.pooled for report in reports]
    spearman = _spread([item.spearman_ensemble for item in pooled])
    miss = _spread([item.miss_rate for item in pooled])
    false_alarm = _spread([item.false_alarm_rate for item in pooled])
    personas = first.personas
    by_persona = {
        pid: _spread([item.spearman_by_persona.get(pid) for item in pooled]) for pid in personas
    }
    skip = {
        pid: _spread([item.skip_overlap_by_persona.get(pid) for item in pooled]) for pid in personas
    }
    ceiling = first.pooled.human_ceiling
    timings = _timing_spreads(pooled)
    return RepeatedCalibrationReport(
        repeats=len(reports),
        prompt_version=first.prompt_version,
        model=first.model,
        personas=personas,
        stories=first.stories,
        n_cells=first.pooled.n_cells,
        n_readers=first.pooled.n_readers,
        human_ceiling=ceiling,
        spearman_ensemble=spearman,
        spearman_by_persona=by_persona,
        miss_rate=miss,
        false_alarm_rate=false_alarm,
        skip_overlap_by_persona=skip,
        timings=timings,
        exit=_exit_from_spreads(spearman, miss, false_alarm, ceiling),
        runs=reports,
    )


def _timing_spreads(pooled: list[CalibrationMetrics]) -> list[TimingSpread]:
    keys = [(item.story_id, item.secret_id) for item in pooled[0].timings]
    out: list[TimingSpread] = []
    for story_id, secret_id in keys:
        rows = [
            next(
                item
                for item in metrics.timings
                if item.secret_id == secret_id and item.story_id == story_id
            )
            for metrics in pooled
        ]
        scenes = [row.sim_scene for row in rows]
        out.append(
            TimingSpread(
                story_id=story_id,
                secret_id=secret_id,
                human_scene=rows[0].human_scene,
                sim_scenes=scenes,
                stable=len(set(scenes)) == 1,
            )
        )
    return out


def _exit_from_spreads(
    spearman: Spread,
    miss: Spread,
    false_alarm: Spread,
    ceiling: float | None,
) -> ExitCheck:
    base = _exit_check(spearman.mean, ceiling, miss.mean, false_alarm.mean)
    notes = list(base.notes)
    spearman_stable = spearman.low is not None and spearman.low >= base.spearman_target
    miss_stable = miss.high is not None and miss.high < MAX_MISS_RATE
    false_alarm_stable = false_alarm.high is not None and false_alarm.high < MAX_FALSE_ALARM_RATE
    if base.spearman_ok and not spearman_stable:
        notes.append(
            f"spearman min {spearman.low:.2f} crosses target {base.spearman_target:.2f}"
            if spearman.low is not None
            else "spearman undefined in at least one repeat"
        )
    if base.miss_ok and not miss_stable:
        notes.append(
            f"miss rate max {miss.high:.2f} crosses {MAX_MISS_RATE}"
            if miss.high is not None
            else "miss rate undefined in at least one repeat"
        )
    if base.false_alarm_ok and not false_alarm_stable:
        notes.append(
            f"false-alarm max {false_alarm.high:.2f} crosses {MAX_FALSE_ALARM_RATE}"
            if false_alarm.high is not None
            else "false-alarm rate undefined in at least one repeat"
        )
    return ExitCheck(
        spearman_target=base.spearman_target,
        spearman_ok=base.spearman_ok and spearman_stable,
        miss_ok=base.miss_ok and miss_stable,
        false_alarm_ok=base.false_alarm_ok and false_alarm_stable,
        passed=base.spearman_ok
        and spearman_stable
        and base.miss_ok
        and miss_stable
        and base.false_alarm_ok
        and false_alarm_stable,
        notes=notes,
    )


def run_repeats(
    stories: list[CalibrationStory],
    responses: list[HumanResponseSet],
    personas: list[Persona],
    client: Any,
    judge: GuessJudge,
    *,
    repeats: int = 1,
    model: str = "",
    resamples: int = 200,
    seed: int = 0,
    workers: int = 4,
    on_repeat: Any | None = None,
) -> RepeatedCalibrationReport:
    """Run the simulator `repeats` times. Identical guesses are judged once."""

    if repeats < 1:
        raise ValueError("repeats must be >= 1")
    cached = _cached(judge)
    reports: list[CalibrationReport] = []
    for index in range(repeats):
        if on_repeat is not None:
            on_repeat(index + 1, repeats)
        reports.append(
            run_calibration(
                stories,
                responses,
                personas,
                client,
                cached,
                model=model,
                resamples=resamples,
                seed=seed,
                workers=workers,
            )
        )
    return aggregate_reports(reports)


def format_report(report: CalibrationReport) -> str:
    def num(value: float | None) -> str:
        return "n/a" if value is None else f"{value:.2f}"

    pooled = report.pooled
    lines = [
        f"prompt {report.prompt_version}  model {report.model or '-'}",
        f"stories {', '.join(report.stories)}  readers {pooled.n_readers}  cells {pooled.n_cells}",
        "",
        f"spearman (ensemble)   {num(pooled.spearman_ensemble)}"
        f"   target ≥ {pooled.exit.spearman_target:.2f}",
        f"human ceiling         {num(pooled.human_ceiling)}",
    ]
    for pid, rho in pooled.spearman_by_persona.items():
        lines.append(f"  spearman {pid:<12} {num(rho)}")
    lines += [
        f"miss rate             {num(pooled.miss_rate)}   target < {MAX_MISS_RATE}",
        f"false-alarm rate      {num(pooled.false_alarm_rate)}   target < {MAX_FALSE_ALARM_RATE}",
    ]
    for pid, overlap in pooled.skip_overlap_by_persona.items():
        lines.append(f"  skip overlap {pid:<12} {num(overlap)}")
    lines.append("")
    for timing in pooled.timings:
        status = {True: "MISS", False: "ok", None: "-"}[timing.missed]
        lines.append(
            f"  {timing.story_id}/{timing.secret_id}: human {timing.human_scene or '-'}"
            f"  sim {timing.sim_scene or '-'}  {status}"
        )
    lines += ["", f"exit criteria: {'PASS' if pooled.exit.passed else 'FAIL'}"]
    lines += [f"  note: {note}" for note in pooled.exit.notes]
    return "\n".join(lines)


def format_repeated(report: RepeatedCalibrationReport) -> str:
    def num(spread: Spread) -> str:
        if spread.mean is None:
            return "n/a"
        if spread.low == spread.high:
            return f"{spread.mean:.2f}"
        return f"mean {spread.mean:.2f}  range {spread.low:.2f}–{spread.high:.2f}"

    lines = [
        f"prompt {report.prompt_version}  model {report.model or '-'}  repeats {report.repeats}",
        f"stories {', '.join(report.stories)}  readers {report.n_readers}  cells {report.n_cells}",
        "",
        f"spearman (ensemble)   {num(report.spearman_ensemble)}"
        f"   target ≥ {report.exit.spearman_target:.2f}",
        "human ceiling         "
        + ("n/a" if report.human_ceiling is None else f"{report.human_ceiling:.2f}"),
    ]
    for pid, spread in report.spearman_by_persona.items():
        lines.append(f"  spearman {pid:<12} {num(spread)}")
    lines += [
        f"miss rate             {num(report.miss_rate)}   target < {MAX_MISS_RATE}",
        f"false-alarm rate      {num(report.false_alarm_rate)}   target < {MAX_FALSE_ALARM_RATE}",
    ]
    for pid, spread in report.skip_overlap_by_persona.items():
        lines.append(f"  skip overlap {pid:<12} {num(spread)}")
    lines.append("")
    for timing in report.timings:
        shown = ", ".join(scene or "-" for scene in timing.sim_scenes)
        flag = "stable" if timing.stable else "UNSTABLE"
        lines.append(
            f"  {timing.story_id}/{timing.secret_id}: human {timing.human_scene or '-'}"
            f"  sim [{shown}]  {flag}"
        )
    lines += ["", f"exit criteria: {'PASS' if report.exit.passed else 'FAIL'}"]
    lines += [f"  note: {note}" for note in report.exit.notes]
    return "\n".join(lines)
