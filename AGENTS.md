# Agent notes — NovelForge

P0 through the P5 code path are done. P1 tooling runs on live models. Original
calibration stories in `novelforge/eval/calibration/stories/` are program
fixtures only. Do not ask a person to review `REVIEW.md`, fill a
questionnaire, or judge guesses. Follow the constitution.

Live models: Volcengine Ark agent plan, key in env var `ark_plan_api_key`
(see `novelforge/llm/routing.py`). Live calls belong in `novelforge eval …`
runs, never in pytest; `tests/conftest.py` unsets the key. Do not “helpfully” pass Canon into the writer or the reader
simulator.

**No novel generation without the user's go-ahead.** When the task is to
change code, the framework, or prompts, do not run `plan`, `write`,
`baseline`, or any live run that produces manuscript text or cards. Finish
the change, run the offline tests, report, and ask. Generate only after the
user explicitly confirms.

## Non-negotiable

1. **WriterView is a whitelist.** Construct it only with
   `build_writer_view(BookState, SceneCard)`. `WriterView` is
   `extra="forbid"` and holds public projections only (`PublicSceneCard`,
   `PublicReaderState`, `PublicPOVState`) — never raw `ReaderState`,
   `POVState`, `must_withhold`, `must_reveal`, or `hint_budget`. Hidden secret
   text **and** hidden secret IDs must not appear in its JSON. If a new
   author-only string field appears on `Secret` or `RevealPlanItem`, classify
   it in `SECRET_TEXT_FIELDS` or `PUBLIC_ID_FIELDS` and add a unique token to
   `tests/test_view_isolation.py`. A leak is a merge blocker.
2. **`simulate_reader(manuscript: list[LockedScene], persona, probes)`** must
   not take `Canon`, `SceneCard`, `BookState`, or `WriterView` (not even as
   optional kwargs). `tests/test_constitution.py` checks names and types.
   Probes come from `probes_from_canon`, which rejects questions containing
   the answer.
3. **Tests are offline.** Use `FakeLLMClient`, or `LiteLLMClient(create_fn=...)`
   to exercise routing and tracing. `tests/conftest.py` blocks HTTP and sets
   `LITELLM_LOCAL_MODEL_COST_MAP` (importing litellm otherwise fetches over
   the network). Do not download `bge-m3`.
4. **Confidence bins over floats.** Reader reports use
   `none|hint|suspect|certain`. Do not treat a 0–1 value as a calibrated
   probability.

5. **Guesses meet the truth only in `roles/guess_judge.py`.** The simulator
   reports free-text guesses; the judge (which may read the truth) scores
   them. Humans and simulators are scored by the same judge.
6. **`eval/calibration/example/` is synthetic.** Use it for tests and format
   demos only; never report its numbers as calibration results.

## Scope

The phase plan, exit criteria, and task checklists live in `docs/PLAN.md`.

- Writer, planner, architect, and reviser prompts are in scope. P1 human
  calibration does not block them.
- Do not ask anyone to review guesses, `REVIEW.md`, or questionnaires.
  Do not import 网文章评 / 本章说, and do not add a per-chapter human review.
- Do not add a judge-accuracy review tool or Langfuse dataset export.
- G1 through G10 are implemented. Pace budgets and the tension-curve
  correction run inside `plan` / `write`. Behavior directives drop causal
  clauses; G5 uses the public clue ledger; G7 checks the hint beat, carry,
  strength budget, and whether a clue was planted. G2 rejects a blocked fact
  or another mind. G4 rejects the default banned list and a verbatim style
  sample of at least 12 characters. The reviser rewrites only the offending
  paragraphs for style and POV; length, pace, skim, hooks, and leaks still
  rewrite the scene. Do not wire `bge-m3`. G1 near-match is character bigrams.
  Do not put the clue ledger, POV names, blocked secret IDs, or archived
  questions on WriterView. Chapter summaries are public text and are checked
  by the same leak filter.
- Long-form reader input is summaries plus the last three full scenes
  (`roles/memory.py`, prompt `reader-sim-v2`). Do not add Canon, BookState,
  or WriterView to `simulate_reader`. Human recalibration of v2 is skipped.
- Gates are blocking (literal, pov, directive leak, inference with a one-bin
  tolerance, reveal) or advisory (`GateResult.advisory()`: length, pace,
  style, hint, tension, skim, hooks, retention, theme). Advisory failures get
  one rewrite, then the scene locks. Do not make craft gates blocking again.
- The planner knows the truth and writes `beats`, `plants`, and
  `misdirection` as visible detail; the writer writes a whole chapter.
  `roles/critic.py` (`choose_draft(manuscript, drafts, client, brief, genre)`) picks
  among candidate drafts and, like the reader simulator, never takes Canon,
  SceneCard, BookState, or WriterView. `brief` is plain text rendered from
  the public story layer and public card fields.
- Every book has a public core: `StoryBible.core` (the feeling readers come
  back for), `themes` (questions with an `arc`), and `approach` (engine,
  voice, motifs, principles). Each card carries `theme_beat` and
  `reader_feeling`. The critic writes a `theme_note` per locked chapter into
  `BookState.theme_notes`; the writer sees the last three. `roles/themes.py`
  drafts the core for a kept Canon without one and drops any theme a blind
  reader can solve from.
- Code gates run before the reader simulator. Directive leak checks use the
  `gate` role (the small model), not `reader_sim`. Review marks for canon,
  opening chapters, payoff scenes, and replans are logged and never block.
- `novelforge gates` reads `gate_stats` and names the prompt to edit.
- Genres (`novelforge/genres/`) are rule sets on one engine: prompt slots,
  gate list with tiers, Canon requirements, `beat_fields`, pacing, personas.
  Never fork the engine per genre. The four leak gates (literal, directive,
  inference, reveal) stay blocking in every genre; `Genre.__post_init__`
  enforces it. Gates go through `gates/registry.py` (`GateSpec`); the
  pipeline runs `genre.pre_gates` / `genre.main_gates`, never a hard-coded
  list. `genre_beats` is public text under the same leak checks as `plants`.
  The project genre lives in `projects/<name>/project.yaml`; missing means
  mystery. Built in: `mystery` and `shuangwen` (no secrets required, the
  edge is not a secret, `payoff` gate, `face_slap` / `gain` / `reaction` /
  `spent` beats). A shuangwen edge needs a source the reader can see — a gift from
  an encounter, or a fragment he learns — plus his own scheme. It must not
  level itself, and a maxed-out opening is a last resort. Shuangwen turns on
  `audit_edge`, `audit_cards`, and `require_story` (`roles/audit.py`);
  mystery leaves them empty so its prompt snapshot does not gain calls.
  A failed audit is one redraft, not a loop. If the second pass still fails,
  `PlanRejected` is raised: a failed canon audit does not write `canon.yaml`,
  and a failed card audit does not write `scenes/sc-*.yaml`. `novelforge plan`
  exits 1. Genre-specific wording belongs in slots, not in role skeletons;
  the reviser leak, hint, and skim lines are `reviser.leak` / `hint` / `skim`.
  Shuangwen names `ledger_gain` / `ledger_spent`. Locking a scene folds those
  beat lines into `BookState.ledger_have` and `ledger_spent`; spent lines leave
  the held list, and the next WriterView carries both (empty lists stay out of
  the mystery prompt snapshot). `tests/test_shuangwen.py` fails if mystery words
  leak into 爽文 prompts.
- `tests/test_genre_snapshot.py` pins every mystery prompt byte for byte.
  If a prompt change is intended, regenerate with
  `uv run python tests/prompt_capture.py` and review the diff.
- No vector database, Web UI, or multi-agent chat framework.
- No VN / GalFactory export.
- When you finish a checklist item in `docs/PLAN.md`, tick it in the same
  commit.

## Layout

Package name is `novelforge` at the repo root. CLI commands: `init`,
`version`, `doctor`, `genres`, `plan`, `write`, `baseline`, `rollback_scene`, `gates`,
`serve` (batch console; starts paused), and `eval questionnaire|calibrate|contamination`. `init <name>` creates
`projects/<name>/` with `canon.yaml`, `models.yaml`, `scenes/`, and
`manuscript/`. `plan` fills canon and scene cards; `write` runs
`pipeline.py` through `graph/scene_graph.py` and `graph/book_graph.py`.
`--fake` uses `FakeLLMClient` and does not call a model.

## Commands

```bash
uv sync
uv run pytest
uv run ruff check . && uv run ruff format --check .
uv run novelforge init demo
```
