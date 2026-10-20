"""Plan a book, then write it scene by scene through the scene graph."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from novelforge.gates.registry import GateContext, run_stage
from novelforge.gates.retention import retention_notes
from novelforge.genres import Genre, get_genre, resolve
from novelforge.graph.book_graph import build_book_graph
from novelforge.graph.scene_graph import SceneNodes, build_scene_graph, default_lock_scene
from novelforge.pacing.curve import mean_tension, tension_curve
from novelforge.pacing.pace import correct_upcoming, length_budget, tighten
from novelforge.roles.architect import draft_canon
from novelforge.roles.audit import PlanRejected, continuity_problems, review_text
from novelforge.roles.behavior import behavior_lines
from novelforge.roles.clues import build_clues
from novelforge.roles.critic import choose_draft, render_brief
from novelforge.roles.directives import screen_directives
from novelforge.roles.guess_judge import GuessJudge, effective_confidence
from novelforge.roles.ledger import fold_ledger
from novelforge.roles.memory import (
    apply_memory,
    archive_closed,
    hidden_texts,
    is_opening_scene,
    is_payoff,
    note_review,
    reading_packet,
    scrub_hidden,
    tally_gates,
)
from novelforge.roles.planner import plan_scenes, replan_scene, scrub_secret_text
from novelforge.roles.prose import SceneDeck
from novelforge.roles.reader_sim import probes_from_canon, simulate_reader
from novelforge.roles.reviser import revise_scene, revision_indexes
from novelforge.roles.themes import draft_core, fill_missing_story, has_core, screen_core
from novelforge.roles.writer import draft_scene, write_baseline
from novelforge.schema.canon import Canon
from novelforge.schema.memory import ThemeNote
from novelforge.schema.reader import Persona, POVState, ReaderReport, ReaderState
from novelforge.schema.scene import LockedScene, SceneCard, WriterView
from novelforge.schema.state import BookState
from novelforge.store import (
    load_book,
    load_canon,
    load_cards,
    load_genre_id,
    load_snapshot,
    project_dir,
    save_book,
    save_canon,
    save_cards,
    save_genre_id,
    save_snapshot,
    write_manuscript,
)

THREAD_ID = "book"


def default_personas(genre: Genre | None = None) -> list[Persona]:
    from novelforge.eval.calibration import load_personas

    return load_personas(resolve(genre).personas)


def project_genre(directory: Path) -> Genre:
    return get_genre(load_genre_id(directory))


def _hidden_texts(book: BookState) -> list[str]:
    return hidden_texts(book)


def _without_secrets(questions: list[str], secret_texts: list[str]) -> list[str]:
    kept: list[str] = []
    for question in questions:
        if not question or any(secret and secret in question for secret in secret_texts):
            continue
        if question not in kept:
            kept.append(question)
    return kept


def _previous_questions(book: BookState) -> list[str]:
    secret_texts = _hidden_texts(book)
    gathered: list[str] = []
    for reader in book.reader_states.values():
        gathered.extend(reader.open_questions)
    return _without_secrets(gathered, secret_texts)


def make_scene_nodes(
    client: Any,
    judge: GuessJudge,
    personas: list[Persona],
    *,
    drafts: int = 1,
    genre: Genre | None = None,
) -> SceneNodes:
    rules = resolve(genre)

    def context(state: dict[str, Any], **extra: Any) -> GateContext:
        return GateContext(
            book=state["book"],
            card=state["card"],
            draft=state.get("draft", ""),
            scene_ids=list(state.get("scene_ids") or []),
            personas=personas,
            client=client,
            judge=judge,
            theme_hit=state.get("theme_hit"),
            revision_count=int(state.get("revision_count") or 0),
            inference_tolerance=rules.inference_tolerance,
            **extra,
        )

    def write(state: dict[str, Any]) -> dict[str, Any]:
        book: BookState = state["book"]
        view: WriterView = state["view"]
        candidates = [draft_scene(view, client, genre=rules) for _ in range(max(1, drafts))]
        brief = render_brief(view.story, view.scene) if has_core(view.story) else ""
        verdict = choose_draft(list(book.locked_scenes), candidates, client, brief, genre=rules)
        hidden = _hidden_texts(book)
        notes = _without_secrets(list(verdict.notes), hidden)
        theme_note = scrub_hidden(verdict.theme_note, hidden)
        return {
            "draft": candidates[verdict.choice],
            "critic_notes": notes,
            "theme_hit": verdict.theme_hit,
            "theme_note": theme_note,
        }

    def pre_gates(state: dict[str, Any]) -> dict[str, Any]:
        results = run_stage("pre", rules.pre_gates, context(state))
        book = tally_gates(state["book"], results)
        return {"pre_gate_results": results, "book": book}

    def revise(state: dict[str, Any]) -> dict[str, Any]:
        book: BookState = state["book"]
        card: SceneCard = state["card"]
        view: WriterView = state["view"]
        results = [*state.get("pre_gate_results", []), *state.get("main_gate_results", [])]
        failed = [result for result in results if not result.passed]
        failures = dict(book.gate_failures)
        for result in failed:
            failures[result.gate_id] = failures.get(result.gate_id, 0) + 1
        book = book.model_copy(update={"gate_failures": failures})
        if any(result.gate_id == "skim" and not result.passed for result in results):
            pace = tighten(str(card.pace))
            length = length_budget(pace, rules.length_budget)
            card = card.model_copy(update={"pace": pace, "length": length})
            scene = view.scene.model_copy(update={"pace": pace, "length": card.length})
            view = view.model_copy(update={"scene": scene})
        if any(result.gate_id == "directive" and not result.passed for result in failed):
            leaked = any(
                reason == "directive leak" for result in failed for reason in result.reasons
            )
            cleaned = [] if leaked else behavior_lines(card.directives)
            plants = [] if leaked else list(card.plants)
            theme_beat = "" if leaked else card.theme_beat
            card = card.model_copy(
                update={"directives": cleaned, "plants": plants, "theme_beat": theme_beat}
            )
            scene = view.scene.model_copy(update={"plants": list(plants), "theme_beat": theme_beat})
            view = view.model_copy(update={"directives": list(cleaned), "scene": scene})
        reasons = [reason for result in failed for reason in result.reasons]
        reasons.extend(f"编辑意见：{note}" for note in state.get("critic_notes") or [])
        if any(result.gate_id == "retention" for result in failed):
            reasons.extend(
                retention_notes(list(state.get("reader_reports") or []), _hidden_texts(book))
            )
        pov = book.pov_states.get(card.pov_character_id)
        others = [item for key, item in book.pov_states.items() if key != card.pov_character_id]
        indexes = revision_indexes(
            state.get("draft", ""),
            results,
            samples=list(book.style_samples),
            pov=pov,
            secrets=book.canon.secrets,
            others=others,
        )
        return {
            "draft": revise_scene(
                view,
                state.get("draft", ""),
                reasons,
                client,
                only_paragraphs=indexes,
                genre=rules,
            ),
            "card": card,
            "view": view,
            "book": book,
        }

    def reader_sim(state: dict[str, Any]) -> dict[str, Any]:
        book: BookState = state["book"]
        card: SceneCard = state["card"]
        manuscript = [*book.locked_scenes, LockedScene.lock(card.scene_id, state.get("draft", ""))]
        packet = reading_packet(manuscript, book.summaries, _hidden_texts(book))
        probes = probes_from_canon(book.canon, set(book.revealed_secret_ids))
        secrets = {secret.id: secret for secret in book.canon.secrets}
        reports: list[ReaderReport] = []
        judged: dict[str, dict[str, str]] = {}
        for persona in personas:
            report = simulate_reader(packet, persona, probes, client=client)
            reports.append(report)
            levels: dict[str, str] = {}
            for guess in report.guesses:
                secret = secrets.get(guess.probe_id)
                if secret is None:
                    continue
                verdict = judge.judge(secret.id, secret.probe_question, secret.text, guess.guess)
                levels[secret.id] = effective_confidence(verdict, guess.confidence)
            judged[persona.id] = levels
        book = book.model_copy(update={"reader_sim_calls": book.reader_sim_calls + len(personas)})
        return {"reader_reports": reports, "judged": judged, "book": book}

    def main_gates(state: dict[str, Any]) -> dict[str, Any]:
        book: BookState = state["book"]
        reports: list[ReaderReport] = list(state.get("reader_reports") or [])
        wants = _without_secrets(
            [question for report in reports for question in report.wants_to_know],
            _hidden_texts(book),
        )
        gate_context = context(
            state,
            reports=reports,
            judged=state.get("judged") or {},
            wants=wants,
            previous_questions=_previous_questions(book),
        )
        results = run_stage("main", rules.main_gates, gate_context)
        return {"main_gate_results": results, "book": tally_gates(book, results)}

    def update_state(state: dict[str, Any]) -> dict[str, Any]:
        book: BookState = state["book"]
        card: SceneCard = state["card"]
        readers = dict(book.reader_states)
        reports = {report.persona_id: report for report in state.get("reader_reports") or []}
        secret_texts = _hidden_texts(book)
        for persona_id, levels in (state.get("judged") or {}).items():
            previous = readers.get(persona_id) or ReaderState(persona_id=persona_id)
            report = reports.get(persona_id)
            questions = (
                _without_secrets(list(report.wants_to_know), secret_texts)
                if report
                else previous.open_questions
            )
            readers[persona_id] = previous.model_copy(
                update={
                    "last_scene_id": card.scene_id,
                    "secret_confidence": {**previous.secret_confidence, **levels},
                    "open_questions": questions,
                }
            )
        revealed = list(book.revealed_secret_ids)
        for secret_id in card.must_reveal:
            if secret_id not in revealed:
                revealed.append(secret_id)
        trace = list(book.tension_trace)
        score = mean_tension([report.tension for report in reports.values()])
        if score is not None:
            trace.append(score)
        archived = archive_closed(book.reader_states, readers, list(book.archived_questions))
        pov_states = dict(book.pov_states)
        if card.pov_character_id:
            previous_pov = pov_states.get(card.pov_character_id) or POVState(
                character_id=card.pov_character_id
            )
            known = list(previous_pov.known_secret_ids)
            for secret_id in card.must_reveal:
                if secret_id not in known:
                    known.append(secret_id)
            pov_states[card.pov_character_id] = previous_pov.model_copy(
                update={
                    "location": card.setting or previous_pov.location,
                    "known_secret_ids": known,
                }
            )
        return {
            "book": book.model_copy(
                update={
                    "reader_states": readers,
                    "revealed_secret_ids": revealed,
                    "tension_trace": trace,
                    "pov_states": pov_states,
                    "archived_questions": archived,
                }
            )
        }

    def replan(state: dict[str, Any]) -> dict[str, Any]:
        book: BookState = state["book"]
        card = replan_scene(book.canon, state["card"], client, note="上一场没通过闸门")
        card = screen_directives(card, book.canon, personas, client, judge)
        book = note_review(book, "replan", state["card"].scene_id)
        return {"card": card, "book": book}

    def lock_scene(state: dict[str, Any]) -> dict[str, Any]:
        updated = default_lock_scene(state)  # type: ignore[arg-type]
        book: BookState = updated["book"]
        card: SceneCard = state["card"]
        note = state.get("theme_note") or ""
        if note:
            entry = ThemeNote(scene_id=card.scene_id, text=note)
            book = book.model_copy(update={"theme_notes": [*book.theme_notes, entry]})
        book = fold_ledger(book, card, rules)
        book = apply_memory(book, client)
        index = len(book.locked_scenes) - 1
        if is_opening_scene(index):
            book = note_review(book, "opening", card.scene_id)
        if is_payoff(book, card):
            book = note_review(book, "payoff", card.scene_id)
        return {"locked": updated["locked"], "book": book}

    return SceneNodes(
        plan_scene=lambda state: {} if state.get("card") else {},
        write=write,
        pre_gates=pre_gates,
        revise=revise,
        reader_sim=reader_sim,
        main_gates=main_gates,
        update_state=update_state,
        replan_scene=replan,
        lock_scene=lock_scene,
    )


def prepare_cards(
    canon: Canon,
    client: Any,
    judge: GuessJudge,
    personas: list[Persona],
    *,
    scenes: int,
    genre: Genre | None = None,
) -> list[SceneCard]:
    rules = resolve(genre)

    def finish(repair: str = "") -> list[SceneCard]:
        cards = [
            screen_directives(card, canon, personas, client, judge)
            for card in plan_scenes(canon, client, scenes=scenes, genre=rules, repair=repair)
        ]
        return scrub_secret_text(cards, canon)

    def problems_in(deck: list[SceneCard]) -> list[str]:
        found = continuity_problems(deck, rules)
        found.extend(
            review_text(
                rules.audit_cards,
                client,
                canon=canon.model_dump_json(),
                cards=SceneDeck(scenes=deck).model_dump_json(),
            )
        )
        return found

    cards = finish()
    if not rules.audit_cards:
        return cards
    problems = problems_in(cards)
    if not problems:
        return cards
    cards = finish("\n".join(f"- {item}" for item in problems))
    remaining = problems_in(cards)
    if remaining:
        raise PlanRejected("；".join(remaining))
    return cards


def run_plan(
    name: str,
    idea: str,
    client: Any,
    judge: GuessJudge,
    *,
    root: Path | None = None,
    scenes: int = 8,
    personas: list[Persona] | None = None,
    keep_canon: bool = False,
    genre: str | None = None,
) -> Path:
    """Draft Canon, then scene cards. `keep_canon` reuses a saved Canon that has secrets.

    `genre` picks the rule set and is saved to project.yaml; without it the
    project's saved genre (or mystery) is used.
    """

    directory = project_dir(name, root)
    directory.mkdir(parents=True, exist_ok=True)
    (directory / "scenes").mkdir(exist_ok=True)
    (directory / "manuscript").mkdir(exist_ok=True)
    (directory / "idea.txt").write_text(idea.strip() + "\n", encoding="utf-8")
    rules = get_genre(genre) if genre else project_genre(directory)
    if genre or load_genre_id(directory):
        save_genre_id(directory, rules.id)
    people = personas if personas is not None else default_personas(rules)
    saved = load_canon(directory) if keep_canon and (directory / "canon.yaml").is_file() else None
    if saved is not None and (saved.secrets or not rules.requires_secrets):
        canon = saved
    else:
        canon = draft_canon(idea, client, scenes=scenes, personas=people, genre=rules)
        save_canon(directory, canon)
    if not canon.story.core and not canon.story.themes:
        canon = draft_core(canon, client, scenes=scenes, genre=rules)
    elif rules.require_story and (not canon.story.core or not canon.story.approach.engine):
        canon = fill_missing_story(canon, client, scenes=scenes)
    if canon != saved:
        canon = screen_core(canon, people, client, judge)
        save_canon(directory, canon)
    cards = prepare_cards(canon, client, judge, people, scenes=scenes, genre=rules)
    save_cards(directory, cards)
    book = BookState(canon=canon, clues=build_clues(cards, canon), pov_states=cast_pov(canon))
    book = note_review(book, "canon")
    save_book(directory, book)
    return directory


def cast_pov(canon: Canon) -> dict[str, POVState]:
    """One viewpoint ledger per named character. Names let G2 catch head-hopping.

    A character is blocked from every secret they are not listed as knowing.
    """

    states: dict[str, POVState] = {}
    for person in canon.story.characters:
        blocked = [
            secret.id
            for secret in canon.secrets
            if not any(person.name and person.name in who for who in secret.known_by)
        ]
        states[person.id] = POVState(
            character_id=person.id,
            name=person.name,
            goal=person.want if person.role == "protagonist" else "",
            blocked_secret_ids=blocked,
        )
    return states


def run_scene(
    book: BookState,
    card: SceneCard,
    scene_ids: list[str],
    client: Any,
    judge: GuessJudge,
    personas: list[Persona],
    *,
    drafts: int = 1,
    genre: Genre | None = None,
) -> dict[str, Any]:
    nodes = make_scene_nodes(client, judge, personas, drafts=drafts, genre=genre)
    graph = build_scene_graph(nodes)
    return graph.invoke(
        {"book": book, "card": card, "scene_ids": scene_ids, "path": []},
        {"recursion_limit": 40},
    )


def run_write(
    name: str,
    client: Any,
    judge: GuessJudge,
    *,
    root: Path | None = None,
    personas: list[Persona] | None = None,
    checkpointer: Any | None = None,
    drafts: int = 1,
    limit: int | None = None,
) -> BookState:
    """Write every card, or the first `limit`. Each chapter gets `drafts` candidates."""

    directory = project_dir(name, root)
    canon = load_canon(directory)
    cards = load_cards(directory)
    current = load_book(directory) or BookState(canon=canon)
    current = current.model_copy(update={"canon": canon})
    rules = project_genre(directory)
    people = personas if personas is not None else default_personas(rules)
    scene_ids = [card.scene_id for card in cards]
    done = {scene.scene_id for scene in current.locked_scenes}

    def write_one(state: dict[str, Any]) -> dict[str, Any]:
        nonlocal current
        cursor = int(state.get("cursor", 0))
        if cursor >= len(cards) or (limit is not None and cursor >= limit):
            return {}
        card = correct_upcoming(
            cards[cursor],
            cursor,
            tension_curve(len(cards), rules.knots),
            list(current.tension_trace),
            rules.length_budget,
        )[0]
        if card.scene_id in done:
            return {}
        save_snapshot(directory, card.scene_id, current)
        result = run_scene(
            current, card, scene_ids, client, judge, people, drafts=drafts, genre=rules
        )
        if result.get("status") != "locked":
            save_book(directory, current)
            raise RuntimeError(f"{card.scene_id} escalated before it could be locked")
        current = result["book"]
        save_book(directory, current)
        write_manuscript(directory, current)
        done.add(card.scene_id)
        return {}

    graph = build_book_graph(write_one, checkpointer=checkpointer)
    config = {"configurable": {"thread_id": THREAD_ID}, "recursion_limit": max(30, len(cards) * 4)}
    if checkpointer is not None and graph.get_state(config).values:
        graph.invoke(None, config)
    else:
        graph.invoke(
            {"cursor": 0, "card_count": len(cards), "project": name, "status": "running"},
            config,
        )
    write_manuscript(directory, current)
    return current


def run_baseline(
    name: str,
    idea: str,
    client: Any,
    *,
    root: Path | None = None,
    scenes: int = 8,
) -> Path:
    directory = project_dir(name, root)
    manuscript = directory / "manuscript"
    manuscript.mkdir(parents=True, exist_ok=True)
    text = write_baseline(idea, client, scenes=scenes, genre=project_genre(directory))
    path = manuscript / "baseline.md"
    path.write_text(text + "\n", encoding="utf-8")
    return path


def rollback(
    name: str, scene_id: str, *, root: Path | None = None, checkpointer: Any | None = None
) -> BookState:
    """Restore the book to the snapshot taken before `scene_id`, and drop later work."""

    directory = project_dir(name, root)
    restored = load_snapshot(directory, scene_id)
    cards = load_cards(directory)
    scene_ids = [card.scene_id for card in cards]
    if scene_id not in scene_ids:
        raise KeyError(scene_id)
    index = scene_ids.index(scene_id)
    for later in scene_ids[index:]:
        snapshot = directory / "snapshots" / f"{later}.yaml"
        if snapshot.is_file():
            snapshot.unlink()
    save_book(directory, restored)
    write_manuscript(directory, restored)
    if checkpointer is not None:
        graph = build_book_graph(checkpointer=checkpointer)
        config = {"configurable": {"thread_id": THREAD_ID}}
        graph.update_state(
            config,
            {"cursor": index, "card_count": len(cards), "project": name, "status": "running"},
            as_node="route",
        )
    return restored
