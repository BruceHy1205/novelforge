"""Built-in gates, adapted to `GateContext`."""

from __future__ import annotations

from novelforge.gates.behavior import check_directives
from novelforge.gates.hint import check_hint
from novelforge.gates.hooks import check_hooks
from novelforge.gates.inference import check_inference, check_reveal_authority
from novelforge.gates.length import check_length
from novelforge.gates.literal import check_literal
from novelforge.gates.pace import check_pace
from novelforge.gates.payoff import check_payoff
from novelforge.gates.pov import check_pov
from novelforge.gates.registry import GateContext, GateSpec, register_gate
from novelforge.gates.retention import GOLDEN_SCENES, check_retention
from novelforge.gates.skim import check_skim
from novelforge.gates.style import check_style
from novelforge.gates.tension import check_tension
from novelforge.schema.canon import iter_secret_texts
from novelforge.schema.gate import GateResult


def _literal(ctx: GateContext) -> GateResult:
    revealed = set(ctx.book.revealed_secret_ids) | set(ctx.card.must_reveal)
    texts = [text for _, text in iter_secret_texts(ctx.book.canon, revealed)]
    return check_literal(ctx.draft, texts)


def _pov(ctx: GateContext) -> GateResult:
    card_pov = ctx.card.pov_character_id
    pov = ctx.book.pov_states.get(card_pov)
    others = [item for key, item in ctx.book.pov_states.items() if key != card_pov]
    return check_pov(ctx.draft, pov, secrets=ctx.book.canon.secrets, others=others)


def _directive_cheap(ctx: GateContext) -> GateResult:
    return check_directives(
        ctx.card, ctx.book.canon, ctx.personas, ctx.client, ctx.judge, leak=False
    )


def _directive(ctx: GateContext) -> GateResult:
    return check_directives(ctx.card, ctx.book.canon, ctx.personas, ctx.client, ctx.judge)


def _theme(ctx: GateContext) -> GateResult | None:
    if ctx.revision_count or ctx.theme_hit is not False:
        return None
    return GateResult(
        gate_id="theme",
        passed=False,
        reasons=["theme: 主题落点和核心体验没有落地，见编辑意见"],
    )


def _inference(ctx: GateContext) -> GateResult:
    return check_inference(
        ctx.judged,
        ctx.book.canon,
        ctx.card.scene_id,
        ctx.scene_ids,
        ctx.book.clues,
        tolerance=ctx.inference_tolerance,
    )


def _hint(ctx: GateContext) -> GateResult:
    budget = ctx.card.hint_budget if isinstance(ctx.card.hint_budget, str) else None
    return check_hint(
        ctx.judged, ctx.book.canon, ctx.card.scene_id, ctx.scene_ids, ctx.book.clues, budget
    )


def _hooks(ctx: GateContext) -> GateResult:
    return check_hooks(
        ctx.draft,
        ending_hook=ctx.card.ending_hook,
        answers_hook=ctx.card.answers_hook,
        previous_questions=ctx.previous_questions,
        wants_to_know=ctx.wants,
        is_last=bool(ctx.scene_ids) and ctx.card.scene_id == ctx.scene_ids[-1],
    )


for spec in (
    GateSpec("literal", "pre", _literal),
    GateSpec("pov", "pre", _pov),
    GateSpec("length", "pre", lambda ctx: check_length(ctx.draft, ctx.card.length)),
    GateSpec("pace", "pre", lambda ctx: check_pace(ctx.draft, str(ctx.card.pace))),
    GateSpec(
        "style",
        "pre",
        lambda ctx: check_style(
            ctx.draft, list(ctx.book.banned_patterns), list(ctx.book.style_samples)
        ),
    ),
    GateSpec("directive", "pre", _directive_cheap, deferred=_directive, prompt="planner"),
    GateSpec("theme", "pre", _theme),
    GateSpec("inference", "main", _inference),
    GateSpec(
        "reveal",
        "main",
        lambda ctx: check_reveal_authority(
            ctx.judged, ctx.book.canon, ctx.card.scene_id, ctx.scene_ids
        ),
    ),
    GateSpec("hint", "main", _hint, prompt="planner"),
    GateSpec("tension", "main", lambda ctx: check_tension(ctx.reports, ctx.card.tension_target)),
    GateSpec(
        "skim", "main", lambda ctx: check_skim(ctx.draft, ctx.reports, scene_id=ctx.card.scene_id)
    ),
    GateSpec("hooks", "main", _hooks, prompt="planner"),
    GateSpec(
        "payoff",
        "main",
        lambda ctx: check_payoff(ctx.draft, ctx.card, ctx.book.canon.story, ctx.client),
    ),
    GateSpec(
        "retention",
        "main",
        lambda ctx: check_retention(
            ctx.reports, opening=len(ctx.book.locked_scenes) < GOLDEN_SCENES
        ),
        prompt="architect",
    ),
):
    register_gate(spec)
