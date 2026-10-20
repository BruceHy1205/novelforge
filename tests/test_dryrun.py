"""The dry-run planner reads the whole scene range, including chapters past 99."""

from __future__ import annotations

from novelforge.factory.dryrun import dry_run_client
from novelforge.roles.prose import SceneDeck


def _ids(prompt: str) -> list[str]:
    deck = dry_run_client().complete(
        [{"role": "user", "content": prompt}],
        SceneDeck,
        role="planner",
    )
    return [card.scene_id for card in deck.scenes]


def test_dry_run_reads_full_scene_ids_past_two_digits() -> None:
    assert _ids("这一次只写 sc-01 到 sc-03，共 3 张。") == ["sc-01", "sc-02", "sc-03"]
    assert _ids("这一次只写 sc-98 到 sc-100，共 3 张。") == ["sc-98", "sc-99", "sc-100"]
    assert _ids("这一次只写 sc-100 到 sc-102，共 3 张。") == ["sc-100", "sc-101", "sc-102"]
    assert _ids("没有批次标记") == ["sc-01", "sc-02", "sc-03"]
