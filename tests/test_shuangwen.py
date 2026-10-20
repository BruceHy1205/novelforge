from __future__ import annotations

from pathlib import Path

from pydantic import BaseModel

from novelforge.gates.payoff import FIX, PayoffReport, check_payoff
from novelforge.genres import get_genre
from novelforge.genres.base import fill
from novelforge.llm.fake import FakeLLMClient
from novelforge.pacing.curve import tension_curve
from novelforge.pipeline import default_personas, run_plan, run_scene
from novelforge.roles import architect, critic, guess_judge, planner, reviser, themes, writer
from novelforge.roles.guess_judge import KeywordJudge
from novelforge.roles.ledger import fold_ledger
from novelforge.roles.memory import prompt_for_gate
from novelforge.roles.prose import Prose, SceneDeck
from novelforge.schema.canon import Canon
from novelforge.schema.reader import Persona, ReaderReport
from novelforge.schema.scene import SceneCard
from novelforge.schema.state import BookState
from novelforge.schema.story import Character, PlausibilityReport, StoryBible
from novelforge.store import load_cards, load_genre_id
from novelforge.view.filter import build_writer_view

SHUANG = get_genre("shuangwen")
MYSTERY_WORDS = ("凶手", "嫌疑", "悬疑", "推理", "作案", "手法", "案子", "异样")

STORY = StoryBible(
    hook="被退婚的废物少爷，手里有一本能看见别人底牌的账簿",
    core="被所有人看不起，却一次次当面扳回一城的痛快",
    protagonist_id="c1",
    characters=[
        Character(id="c1", name="林舟", role="protagonist", edge="账簿能看见对手手里的底牌"),
        Character(id="c2", name="赵恒", role="antagonist", surface_motive="想吞林家的铺子"),
    ],
)


def _prompts() -> dict[str, str]:
    return {
        "pitch": architect.pitch_prompt(SHUANG),
        "architect": architect.system_prompt(SHUANG),
        "planner": planner.system_prompt(SHUANG),
        "writer": writer.system_prompt(SHUANG),
        "reviser": reviser.system_prompt(SHUANG),
        "critic": critic.system_prompt(SHUANG),
        "themes": fill(themes.PROMPT_TEMPLATE, SHUANG, "themes"),
        "judge": fill(guess_judge.JUDGE_TEMPLATE, SHUANG, "judge"),
        "plausibility": SHUANG.prompt("plausibility"),
    }


def test_shuangwen_is_registered_with_its_own_readers() -> None:
    assert SHUANG.name == "爽文"
    assert not SHUANG.requires_secrets
    assert set(SHUANG.required_roles) == {"protagonist", "antagonist"}
    people = default_personas(SHUANG)
    assert len(people) == 3
    assert {person.id for person in people} != {person.id for person in default_personas()}


def test_shuangwen_prompts_carry_no_mystery_rules() -> None:
    for role, text in _prompts().items():
        leftovers = [word for word in MYSTERY_WORDS if word in text]
        assert not leftovers, f"{role} prompt still says {leftovers}"
    prompts = _prompts()
    assert "打脸" in prompts["planner"] and "face_slap" in prompts["planner"]
    assert "爽点要写足" in prompts["writer"]
    assert "反派不能降智" in prompts["architect"]
    assert "0 到 2 个秘密" in prompts["architect"]
    assert "被退婚" in prompts["planner"]
    assert "残方" in prompts["architect"] and "计谋" in prompts["architect"]
    assert "废材吃了废材" in prompts["architect"]
    assert "上一章结尾" in prompts["planner"]
    assert "看见因果" in prompts["writer"]
    assert "已经用掉的东西不要写回来" in prompts["reviser"]
    assert "ledger_have" in prompts["writer"]
    mystery_reviser = reviser.system_prompt()
    assert "看得见的异样" in mystery_reviser
    assert "推动悬念" in mystery_reviser
    assert "ledger_have" not in writer.system_prompt()


def test_shuangwen_pacing_is_a_wave() -> None:
    curve = tension_curve(8, SHUANG.knots)
    assert curve[0] >= 0.75
    assert curve[-1] > 0.9
    dips = sum(1 for before, after in zip(curve, curve[1:], strict=False) if after < before)
    assert dips >= 2
    assert SHUANG.length_budget["sprint"] < SHUANG.length_budget["slack"]
    assert "爆发" in SHUANG.pace_craft["sprint"] and "蓄力" in SHUANG.pace_craft["slack"]


def test_payoff_gate_passes_a_landed_chapter() -> None:
    card = SceneCard(
        scene_id="sc-03",
        payoff="当众拆穿赵恒的假账",
        genre_beats={"face_slap": ["赵恒当众要林舟下跪"], "gain": ["拿回城东铺子"]},
    )
    client = FakeLLMClient(canned={PayoffReport: PayoffReport(release="拆穿假账", gain="铺子")})
    result = check_payoff("赵恒冷笑。\n林舟翻开账簿。", card, STORY, client)
    assert result.passed
    prompt = client.calls[0]["messages"][0]["content"]
    assert "赵恒当众要林舟下跪" in prompt and "账簿能看见对手手里的底牌" in prompt
    assert "[¶1] 林舟翻开账簿。" in prompt
    assert client.calls[0]["role"] == "gate"


def test_payoff_gate_explains_a_flat_chapter() -> None:
    report = PayoffReport(landed=False, problems=["¶4 一句“他赢了”带过"])
    client = FakeLLMClient(canned={PayoffReport: report})
    result = check_payoff("他赢了。", SceneCard(scene_id="sc-02"), STORY, client)
    assert not result.passed
    assert "¶4 一句“他赢了”带过" in result.reasons
    assert f"payoff: {FIX}" in result.reasons
    assert prompt_for_gate("payoff") == "writer"


def test_plan_without_secrets_runs_the_setting_review(tmp_path: Path) -> None:
    card = SceneCard(
        scene_id="sc-01",
        title="退婚",
        ending_hook="调令拍下来了",
        answers_hook="他揣着调令到了门前",
        genre_beats={
            "face_slap": ["赵恒当众撕了婚书"],
            "gain": ["账簿第一次亮了"],
            "reaction": ["满堂改口"],
            "spent": ["婚书烧了"],
            "mystery_only": ["丢掉"],
        },
    )

    def respond(messages: list[dict[str, str]], model: type[BaseModel]) -> BaseModel | None:
        if model is Canon:
            return Canon(title="账簿", story=STORY)
        if model is SceneDeck:
            return SceneDeck(scenes=[card, card])
        if model is PlausibilityReport:
            return PlausibilityReport()
        return None

    client = FakeLLMClient(responder=respond)
    run_plan(
        "zhang",
        "被退婚的少爷",
        client,
        KeywordJudge({}),
        root=tmp_path,
        scenes=2,
        personas=[Persona(id="p")],
        genre="shuangwen",
    )
    directory = tmp_path / "projects" / "zhang"
    assert load_genre_id(directory) == "shuangwen"
    reviews = [call for call in client.calls if call["response_model"] == "PlausibilityReport"]
    assert reviews and "爽文网文的资深审稿人" in reviews[0]["messages"][0]["content"]
    cards = load_cards(directory)
    assert set(cards[0].genre_beats) == {"face_slap", "gain", "reaction", "spent"}


def test_a_flat_payoff_gets_one_rewrite_with_the_reasons() -> None:
    payoffs = iter([PayoffReport(landed=False, problems=["¶1 出手没写反应"]), PayoffReport()])

    def respond(messages: list[dict[str, str]], model: type[BaseModel]) -> BaseModel | None:
        if model is Prose:
            return Prose(text="赵恒冷笑。\n林舟翻开账簿。\n满堂的人都不说话了。")
        if model is ReaderReport:
            return ReaderReport(persona_id="p", tension="high")
        if model is PayoffReport:
            return next(payoffs, PayoffReport())
        return None

    client = FakeLLMClient(responder=respond)
    result = run_scene(
        BookState(canon=Canon(story=STORY)),
        SceneCard(scene_id="sc-01", length=20, pace="steady", tension_target=0.75),
        ["sc-01"],
        client,
        KeywordJudge({}),
        [Persona(id="p")],
        genre=SHUANG,
    )
    assert result["status"] == "locked"
    revisions = [call for call in client.calls if call["role"] == "reviser"]
    assert revisions
    assert any("¶1 出手没写反应" in message["content"] for message in revisions[0]["messages"])
    assert result["book"].gate_stats["payoff"].failures == 1


def test_the_ledger_drops_what_this_chapter_spent() -> None:
    card = SceneCard(
        scene_id="sc-02",
        genre_beats={"gain": ["火符残页", "旧丹"], "spent": ["旧丹"]},
    )
    book = BookState(canon=Canon(story=STORY), ledger_have=["旧丹"])
    folded = fold_ledger(book, card, SHUANG)
    assert folded.ledger_have == ["火符残页"]
    assert folded.ledger_spent == ["旧丹"]
    assert fold_ledger(folded, card, SHUANG) is folded
    assert fold_ledger(book, card, get_genre("mystery")) is book


def test_the_writer_view_carries_the_ledger_and_hides_an_empty_one() -> None:
    state = BookState(canon=Canon(story=STORY), ledger_have=["火符残页"], ledger_spent=["旧丹"])
    view = build_writer_view(state, SceneCard(scene_id="sc-02"))
    assert view.ledger_have == ["火符残页"]
    assert view.ledger_spent == ["旧丹"]
    empty = build_writer_view(BookState(canon=Canon(story=STORY)), SceneCard(scene_id="sc-01"))
    dumped = empty.model_dump()
    assert "ledger_have" not in dumped
    assert "ledger_spent" not in empty.model_dump_json()


def test_locking_a_scene_records_gain_and_spent() -> None:
    def respond(messages: list[dict[str, str]], model: type[BaseModel]) -> BaseModel | None:
        if model is Prose:
            return Prose(text="赵恒冷笑。\n林舟翻开账簿。\n满堂的人都不说话了。")
        if model is ReaderReport:
            return ReaderReport(persona_id="p", tension="high")
        if model is PayoffReport:
            return PayoffReport()
        return None

    result = run_scene(
        BookState(canon=Canon(story=STORY), ledger_have=["火晶", "残页"]),
        SceneCard(
            scene_id="sc-02",
            length=20,
            pace="steady",
            tension_target=0.75,
            genre_beats={"gain": ["一枚温丹"], "spent": ["火晶"]},
        ),
        ["sc-02"],
        FakeLLMClient(responder=respond),
        KeywordJudge({}),
        [Persona(id="p")],
        genre=SHUANG,
    )
    book = result["book"]
    assert book.ledger_have == ["残页", "一枚温丹"]
    assert book.ledger_spent == ["火晶"]
