"""Mystery: a hidden truth, fair-play clues, and suspects. The original rule set."""

from __future__ import annotations

from novelforge.eval.calibration import data_path
from novelforge.genres.base import Genre
from novelforge.pacing.curve import KNOTS
from novelforge.pacing.pace import LENGTH_BUDGET, PACE_CRAFT

PROMPTS: dict[str, str] = {
    "pitch.identity": "网文悬疑的策划编辑",
    "pitch.protagonist": "  主角必须被卷进案子，有个人代价，不能只是来记录现场的警察。",
    "architect.identity": "网文悬疑的架构师",
    "architect.cast": """\
- characters：主角 1 人（role=protagonist），嫌疑人 3 到 5 人（role=suspect），死者，关键证人。
  每人写 id（如 char-1）、name、public_face（别人眼里的他）、want、stake（会失去什么）。
  主角写 edge：他的金手指或信息差，规则简单、一句话能说清，能在第一到三章用上。
  嫌疑人写 surface_motive 和 surface_opportunity：表面上的动机和作案机会。
  每个嫌疑人都要显得可能是凶手。真凶必须在嫌疑人里，但 public_face 只写表象。""",
    "architect.why": """\
- core：核心体验，一句话。读者每章回来追的那种感觉，要具体到情绪，
  例如“被所有人当成没用的人，却一次次用只有他能做到的方式扳回一城的爽”
  或“明知道真相会伤人还得一层层剥开的揪心”。全书每一章都要喂这种感觉。
- themes：一到三个主题。每个写 id（T-1…）、question（主题追问，写成问题，
  例如“没人肯听的证词还算不算证词？”）、tension（两种都有道理的回答，人物会站在不同的一边）、
  arc（三到五步，主角对这个问题的回答怎样随故事变化：起点、动摇、代价、新的回答）。
  主题围绕主角的处境、关系和选择，不要指向谁是凶手、谁在撒谎、手法是什么。
- approach：写作思路。
  engine：叙事引擎，每章重复并升级的阅读动力，例如“每章他看见一件别人看不见的事，
  证明一次自己，又因此付出更大的代价”。
  voice：叙述声音，例如“贴着主角感官的近距离第三人称，冷、克制，痛处一笔带过”。
  motifs：两到四个反复出现的意象或物件，每次出现意义都往前走一步。
  principles：两到四条这本书的写法原则（例如“情绪落在动作上，不落在形容词上”）。""",
    "architect.secret_count": "2 到 4 个秘密",
    "architect.secrets": """\
- 手法必须在现实中能做到：不要遥控刀刃、不要只有作者知道的机关、不要靠巧合。
- 公平推理：破案需要的每条线索都要能在揭晓前被读者看到。""",
    "plausibility": """你是本格推理的审稿人。检查下面的 Canon。

- plausible：作案手法在现实里能不能做到，凶手的行动和时间线是否自洽。
- fair_play：读者能不能凭揭晓前可见的线索推出真相，有没有靠巧合或临时冒出的新人新工具。
- problems：列出最严重的问题，每条一句话。没有就留空。

Canon：
{canon}""",
    "themes.identity": "这本悬疑网文的主编",
    "themes.core": "  爽文也要说清楚爽在哪里；悬疑要说清楚揪心、不安或扳回一城的快感落在哪。",
    "themes.guard": "  主题长在主角的处境、关系和选择上，不要指向谁是凶手、谁在撒谎、手法是什么。",
    "planner.identity": "网文悬疑的总编剧",
    "planner.mission": "你的工作是把真相变成读者回头能对上的叙事，而写手只看到可见的细节。",
    "planner.stakes": "关系、处境、筹码、嫌疑人排序",
    "planner.beats": """\
  要有铺垫：先让读者看见日常、主角的处境、他在乎的人和事，再让异样一点点渗进来。
  要有转折：至少一处读者以为是 A、其实变成 B 的时刻（误判、新信息、关系翻面）。
  可以写主角的回忆、判断、恐惧和欲望，可以写对话里的潜台词和氛围。""",
    "planner.craft": """\
- plants：伏笔，一到三条。用你知道的真相，设计读者第一次读会滑过去、真相揭开后能对上的可见细节。
  只写看得见的东西（物件、动作、一句话、一个反常的位置），不要写它意味着什么。
- misdirection：误导，零到两条。可见的细节，让读者把怀疑放到错误的人或方向上。要公平，不能撒谎。""",
    "planner.no_spoil": "说出谜底、点名凶手",
    "planner.opening": """\
- sc-01 入局：三百字内要有让人不安的异样（一条消息、一个声音、一处反常），本章前半核心事件发生。
  在异样之前或之间，让读者认识主角：他是谁、现在过得怎样、想要什么、和这件事有什么牵连。
  日常和异常的对比要清楚，发现才有冲击力。
- sc-02 加压：阻力升级，规则露出，问题比想象中更贴近主角。
- sc-03 承诺：亮出主角的优势或信息差，给出全书主线的长期追读理由。
钩子要一章比一章更贴近主角：风险更具体，关系更贴身，选择更难撤回。""",
    "writer.identity": "成熟的网文悬疑作者",
    "writer.craft": """\
- scene.plants 是伏笔：自然地放进场景里，和别的细节混在一起，不要强调，不要解释。
- scene.misdirection 是可见的误导细节：写出来，让读者自己起疑，不要点明。""",
    "writer.opening": """\
- “入局”：三百字内出现让人不安的异样，本章前半核心事件发生；
  在这之前或之间，让读者认识主角的日常和处境，日常和异常对比要清楚。
- “加压”：问题升级，更贴近主角，代价变具体。
- “承诺”：亮出主角的 edge，给出长期追读的理由。""",
    "critic.identity": "在网文平台追悬疑小说的老读者，也是挑剔的编辑",
    "critic.craft": "- 有没有转折、潜台词和让你自己起疑的细节。",
    "critic.setup": "- 有没有铺垫和氛围，日常和异样的对比，而不是一上来罗列现场。",
    "reviser.leak": (
        "- 若问题是泄底或读者猜得太快：删掉点破答案的那几句，把结论换回一个看得见的异样。"
    ),
    "reviser.hint": "- 若问题是暗示没落地：保留一个看得见的异常，但不要点明含义。",
    "reviser.skim": (
        "- 若问题含 skip rate，或段落太长：压缩读者想跳过的段落，删掉重复，保留推动悬念的细节。"
    ),
    "judge.identity": "悬疑小说的判卷人",
    "judge.examples": "凶手身份、关键动机",
    "baseline.kind": "悬疑短篇",
}

MYSTERY = Genre(
    id="mystery",
    name="悬疑推理",
    prompts=PROMPTS,
    pre_gates=(
        ("literal", "blocking"),
        ("pov", "blocking"),
        ("length", "advisory"),
        ("pace", "advisory"),
        ("style", "advisory"),
        ("directive", "blocking"),
        ("theme", "advisory"),
    ),
    main_gates=(
        ("inference", "blocking"),
        ("reveal", "blocking"),
        ("hint", "advisory"),
        ("tension", "advisory"),
        ("skim", "advisory"),
        ("hooks", "advisory"),
        ("retention", "advisory"),
    ),
    knots=KNOTS,
    length_budget=dict(LENGTH_BUDGET),
    pace_craft=dict(PACE_CRAFT),
    personas=data_path("personas.yaml"),
    requires_secrets=True,
    required_roles={"protagonist": "主角", "suspect": "嫌疑人"},
    inference_tolerance=1,
)
