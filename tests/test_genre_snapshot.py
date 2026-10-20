"""The mystery genre must send exactly the prompts it sent before genres existed."""

from __future__ import annotations

import json
from pathlib import Path

from tests.prompt_capture import SNAPSHOT, capture


def test_mystery_prompts_match_the_snapshot(tmp_path: Path) -> None:
    expected = json.loads(SNAPSHOT.read_text(encoding="utf-8"))
    actual = json.loads(json.dumps(capture(tmp_path), ensure_ascii=False))
    assert len(actual) == len(expected)
    for index, (got, want) in enumerate(zip(actual, expected, strict=True)):
        assert got == want, f"call {index} ({want['role']} {want['model']}) changed"
