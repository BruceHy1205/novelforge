"""Chapter craft: beats, plants, misdirection, and the planner/writer prompts."""

from __future__ import annotations

from pathlib import Path

import pytest
from pydantic import BaseModel

from novelforge.llm.fake import FakeLLMClient
from novelforge.pipeline import run_plan, run_scene
from novelforge.roles.behavior import apply_behavior
from novelforge.roles.critic import CriticVerdict, choose_draft
from novelforge.roles.guess_judge import KeywordJudge
from novelforge.roles.planner import SYSTEM_PROMPT as PLANNER_PROMPT
from novelforge.roles.planner import plan_scenes, scrub_secret_text
from novelforge.roles.prose import Prose, SceneDeck
from novelforge.roles.writer import SYSTEM_PROMPT as WRITER_PROMPT
from novelforge.roles.writer import draft_scene
from novelforge.schema.canon import Canon, Secret
from novelforge.schema.reader import Persona, ReaderReport
from novelforge.schema.scene import SceneCard
from novelforge.schema.state import BookState
from novelforge.store import load_canon, load_cards, save_canon
from novelforge.view.filter import SecretLeakError, build_writer_view

SECRET = "凶手用铁丝把钥匙推回屋里"


def _canon() -> Canon:
    return Canon(title="雨棚", secrets=[Secret(id="S-1", title="钥匙", text=SECRET)])


def test_craft_fields_reach_the_writer() -> None:
    card = SceneCard(
        scene_id="sc-01",
        beats=["他被雨声吵醒，看见群里那条消息", "上楼，门虚掩"],
        plants=["地垫边缘一小片反光"],
        misdirection=["一楼修鞋匠脚边那双带泥的雨鞋"],
    )
    view = build_writer_view(BookState(canon=_canon()), card)
    assert view.scene.beats == card.beats
    assert view.scene.plants == card.plants
    assert view.scene.misdirection == card.misdirection


@pytest.mark.parametrize("field", ["beats", "plants", "misdirection"])
def test_a_craft_field_cannot_carry_a_secret(field: str) -> None:
    card = SceneCard(scene_id="sc-01", **{field: [f"写清楚：{SECRET}"]})
    with pytest.raises(SecretLeakError):
        build_writer_view(BookState(canon=_canon()), card)


def test_scrub_drops_secret_lines_from_craft_fields() -> None:
    card = SceneCard(
        scene_id="sc-01",
        beats=["他上楼", SECRET],
        plants=[f"S-1 {SECRET}", "地垫边缘一小片反光"],
        misdirection=["提到 S-1 的雨鞋"],
    )
    clean = scrub_secret_text([card], _canon())[0]
    assert clean.beats == ["他上楼"]
    assert clean.plants == ["地垫边缘一小片反光"]
    assert clean.misdirection == ["提到 的雨鞋"]


def test_plants_and_misdirection_lose_their_cause() -> None:
    card = SceneCard(
        scene_id="sc-01",
        plants=["地垫边缘一道划痕，因为有人推过钥匙"],
        misdirection=["老赵的雨鞋带泥，所以像是他"],
    )
    shaped = apply_behavior(card, _canon())
    assert shaped.plants == ["地垫边缘一道划痕"]
    assert shaped.misdirection == ["老赵的雨鞋带泥"]


def test_critic_picks_a_draft_and_clamps_a_bad_index() -> None:
    single = FakeLLMClient()
    assert choose_draft([], ["甲"], single).choice == 0
    assert single.calls == []
    picked = FakeLLMClient(canned={CriticVerdict: CriticVerdict(choice=1, reason="有铺垫")})
    assert choose_draft([], ["甲", "乙"], picked).choice == 1
    assert picked.calls[0]["role"] == "critic"
    wild = FakeLLMClient(canned={CriticVerdict: CriticVerdict(choice=7)})
    assert choose_draft([], ["甲", "乙"], wild).choice == 0


def test_two_drafts_lock_the_one_the_critic_picks() -> None:
    texts = iter(["平的一稿", "有铺垫的一稿"])

    def respond(_messages: list[dict[str, str]], model: type[BaseModel]) -> BaseModel | None:
        if model is Prose:
            return Prose(text=next(texts))
        if model is CriticVerdict:
            return CriticVerdict(choice=1, notes=[f"别说出{SECRET}", "开头再慢一点"])
        if model is ReaderReport:
            return ReaderReport(persona_id="p", tension="high")
        return None

    client = FakeLLMClient(responder=respond)
    result = run_scene(
        BookState(canon=_canon()),
        SceneCard(scene_id="sc-01", length=6, tension_target=0.3),
        ["sc-01"],
        client,
        KeywordJudge({"S-1": [SECRET]}),
        [Persona(id="p")],
        drafts=2,
    )
    assert result["status"] == "locked"
    assert result["locked"].text == "有铺垫的一稿"
    assert result["critic_notes"] == ["开头再慢一点"]
    roles = [call["role"] for call in client.calls]
    assert roles[:3] == ["writer", "writer", "critic"]


def _planner_client() -> FakeLLMClient:
    def respond(_messages: list[dict[str, str]], model: type[BaseModel]) -> BaseModel | None:
        if model is SceneDeck:
            return SceneDeck(scenes=[SceneCard(scene_id="x", title="t") for _ in range(3)])
        return None

    return FakeLLMClient(responder=respond)


def _planner_ranges(client: FakeLLMClient) -> list[str]:
    return [call["messages"][-1]["content"] for call in client.calls]


def _span_size(label: str) -> int:
    start, end = label.split(" 到 ")
    return int(end.removeprefix("sc-")) - int(start.removeprefix("sc-")) + 1


def test_planner_works_in_batches_of_three() -> None:
    client = _planner_client()
    cards = plan_scenes(_canon(), client, scenes=5)
    assert [card.scene_id for card in cards] == [f"sc-0{index}" for index in range(1, 6)]
    asks = _planner_ranges(client)
    assert len(asks) == 2
    assert "sc-01 到 sc-03" in asks[0]
    assert "共 3 张" in asks[0]
    assert "sc-04 到 sc-05" in asks[1] and "已经规划好的场景卡" in asks[1]
    assert "共 2 张" in asks[1]


@pytest.mark.parametrize(
    ("batch", "ranges"),
    [
        (
            1,
            [
                "sc-01 到 sc-01",
                "sc-02 到 sc-02",
                "sc-03 到 sc-03",
                "sc-04 到 sc-04",
                "sc-05 到 sc-05",
            ],
        ),
        (2, ["sc-01 到 sc-02", "sc-03 到 sc-04", "sc-05 到 sc-05"]),
        (3, ["sc-01 到 sc-03", "sc-04 到 sc-05"]),
    ],
)
def test_planner_scenes_per_batch(batch: int, ranges: list[str]) -> None:
    client = _planner_client()
    cards = plan_scenes(_canon(), client, scenes=5, scenes_per_batch=batch)
    assert [card.scene_id for card in cards] == [f"sc-0{index}" for index in range(1, 6)]
    asks = _planner_ranges(client)
    assert len(asks) == len(ranges)
    for ask, expected in zip(asks, ranges, strict=True):
        assert expected in ask
        assert f"共 {_span_size(expected)} 张" in ask
    assert all("已经规划好的场景卡" in ask for ask in asks[1:])
    assert "已经规划好的场景卡" not in asks[0]


def test_planner_rejects_a_nonpositive_batch() -> None:
    with pytest.raises(ValueError, match="scenes_per_batch"):
        plan_scenes(_canon(), _planner_client(), scenes=1, scenes_per_batch=0)


def test_run_plan_issues_one_scene_per_planner_call(tmp_path: Path) -> None:
    directory = tmp_path / "projects" / "demo"
    directory.mkdir(parents=True)
    save_canon(directory, _canon())
    client = _planner_client()
    run_plan(
        "demo",
        "雨",
        client,
        KeywordJudge({"S-1": [SECRET]}),
        root=tmp_path,
        scenes=3,
        personas=[],
        keep_canon=True,
        scenes_per_batch=1,
    )
    planner = [call for call in client.calls if call["role"] == "planner"]
    asks = [call["messages"][-1]["content"] for call in planner]
    assert len(asks) == 3
    assert "sc-01 到 sc-01" in asks[0] and "共 1 张" in asks[0]
    assert "sc-02 到 sc-02" in asks[1] and "已经规划好的场景卡" in asks[1]
    assert "sc-03 到 sc-03" in asks[2]
    assert [card.scene_id for card in load_cards(directory)] == ["sc-01", "sc-02", "sc-03"]


def test_keep_canon_does_not_redraft_the_canon(tmp_path: Path) -> None:
    def respond(_messages: list[dict[str, str]], model: type[BaseModel]) -> BaseModel | None:
        if model is SceneDeck:
            return SceneDeck(scenes=[SceneCard(scene_id="x")])
        return None

    directory = tmp_path / "projects" / "demo"
    directory.mkdir(parents=True)
    save_canon(directory, _canon())
    client = FakeLLMClient(responder=respond)
    judge = KeywordJudge({"S-1": [SECRET]})
    run_plan("demo", "雨", client, judge, root=tmp_path, scenes=1, personas=[], keep_canon=True)
    models = [call["response_model"] for call in client.calls if call["role"] == "architect"]
    assert models == ["StoryCore"]
    assert load_canon(directory).title == "雨棚"


def test_prompts_ask_for_setup_turns_and_plants() -> None:
    assert "plants" in PLANNER_PROMPT and "misdirection" in PLANNER_PROMPT
    assert "起承转合" in PLANNER_PROMPT and "铺垫" in PLANNER_PROMPT
    assert "scene.plants" in WRITER_PROMPT and "scene.beats" in WRITER_PROMPT
    assert "不要写别人的内心" in WRITER_PROMPT
    client = FakeLLMClient(canned={Prose: Prose(text="雨")})
    draft_scene(build_writer_view(BookState(canon=_canon()), SceneCard(scene_id="sc-01")), client)
    assert "铺垫" in client.calls[0]["messages"][0]["content"]
