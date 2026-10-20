"""Gate verdicts used by the post-write pipeline."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field


class GateResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    gate_id: str
    passed: bool
    score: float | None = None
    reasons: list[str] = Field(default_factory=list)
    details: dict[str, str] = Field(default_factory=dict)
    # A non-blocking failure is advice: it may trigger one rewrite, never an escalation.
    blocking: bool = True

    def advisory(self) -> GateResult:
        return self.model_copy(update={"blocking": False})
