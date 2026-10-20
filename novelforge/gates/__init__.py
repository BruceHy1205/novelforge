"""Post-write gates. G1–G10 run in code. bge-m3 stays unwired."""

from novelforge.gates.hint import check_hint
from novelforge.gates.hooks import check_hooks
from novelforge.gates.inference import check_inference, check_reveal_authority
from novelforge.gates.length import check_length
from novelforge.gates.literal import check_literal
from novelforge.gates.pace import check_pace
from novelforge.gates.pov import check_pov
from novelforge.gates.skim import check_skim
from novelforge.gates.style import check_style
from novelforge.gates.tension import check_tension

GATE_ORDER = (
    "literal",
    "pov",
    "length",
    "pace",
    "style",
    "inference",
    "hint",
    "tension",
    "skim",
    "hooks",
)

__all__ = [
    "GATE_ORDER",
    "check_hint",
    "check_hooks",
    "check_inference",
    "check_reveal_authority",
    "check_length",
    "check_literal",
    "check_pace",
    "check_pov",
    "check_skim",
    "check_style",
    "check_tension",
]
