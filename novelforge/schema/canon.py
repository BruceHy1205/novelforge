"""Author-omniscient Canon. Secret texts never enter WriterView."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from novelforge.schema.story import StoryBible

SecretCategory = Literal["identity", "plot", "world", "history", "motive"]
RevealMethod = Literal["withhold", "hint", "reveal"]

# String fields whose values are author-only. Isolation tests walk this map.
# If you add a new string field to a secret-bearing model, classify it here
# or in PUBLIC_ID_FIELDS — otherwise the completeness test fails.
SECRET_TEXT_FIELDS: dict[str, tuple[str, ...]] = {
    "Secret": ("title", "text", "internal_notes"),
    "RevealPlanItem": ("author_rationale",),
}

PUBLIC_ID_FIELDS: dict[str, tuple[str, ...]] = {
    "Secret": ("id", "category", "probe_question"),
    "RevealPlanItem": (
        "secret_id",
        "earliest_scene_id",
        "method",
        "public_beat_label",
    ),
}


class Secret(BaseModel):
    """One author-omniscient fact. `id` is an opaque handle (e.g. S-001).

    `probe_question` is the public question the reader simulator answers
    (e.g. "谁是凶手？"). It must not contain the answer.
    """

    model_config = ConfigDict(extra="forbid")

    id: str
    category: SecretCategory = "plot"
    title: str
    text: str
    internal_notes: str = ""
    probe_question: str = ""
    known_by: list[str] = Field(default_factory=list)


class RevealPlanItem(BaseModel):
    """When a secret may surface. Author rationale stays off the writer desk."""

    model_config = ConfigDict(extra="forbid")

    secret_id: str
    earliest_scene_id: str | None = None
    method: RevealMethod = "withhold"
    author_rationale: str = ""
    public_beat_label: str = ""


class Canon(BaseModel):
    """Full author knowledge. Construct WriterView via the whitelist filter."""

    model_config = ConfigDict(extra="forbid")

    title: str = ""
    premise: str = ""
    story: StoryBible = Field(default_factory=StoryBible)
    secrets: list[Secret] = Field(default_factory=list)
    reveal_plan: list[RevealPlanItem] = Field(default_factory=list)


def iter_secret_texts(
    canon: Canon,
    exclude_ids: frozenset[str] | set[str] = frozenset(),
) -> list[tuple[str, str]]:
    """Return `(field_path, text)` for every classified secret string.

    Secrets whose IDs are in `exclude_ids` (already revealed, or revealed by
    the current scene) are skipped: their text is public from that point on.
    """

    out: list[tuple[str, str]] = []
    for index, secret in enumerate(canon.secrets):
        if secret.id in exclude_ids:
            continue
        for field_name in SECRET_TEXT_FIELDS["Secret"]:
            value = getattr(secret, field_name)
            if value:
                out.append((f"secrets[{index}].{field_name}", value))
    for index, item in enumerate(canon.reveal_plan):
        if item.secret_id in exclude_ids:
            continue
        for field_name in SECRET_TEXT_FIELDS["RevealPlanItem"]:
            value = getattr(item, field_name)
            if value:
                out.append((f"reveal_plan[{index}].{field_name}", value))
    return out


def hidden_secret_ids(canon: Canon, revealed: frozenset[str] | set[str]) -> list[str]:
    return [secret.id for secret in canon.secrets if secret.id not in revealed]
