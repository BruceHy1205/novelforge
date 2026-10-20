"""Shuangwen (爽文): pressure, then a payoff the protagonist earns, then a bigger stage.

Secrets are optional. The protagonist's edge is not one: readers know it from
chapter one, opponents do not. Long-line mysteries (origin, who is behind it
all) may still be secrets and run under the same leak gates as mystery.
"""

# ruff: noqa: E501  (prompt text: one line per instruction)

from __future__ import annotations

from pathlib import Path

from novelforge.genres.base import Genre

PROMPTS: dict[str, str] = {
    "pitch.identity": "网文爽文的策划编辑",
    "pitch.protagonist": (
        "  主角起点要低、受的气要具体；他的金手指或底牌规则简单、一句话说清、第一章就露头；"
        "他想要的东西要大到能撑起整本书。"
    ),
    "architect.identity": "网文爽文的架构师",
    "architect.cast": """\
- characters：主角 1 人（role=protagonist），反派 2 到 4 人（role=antagonist），
  盟友一到两人（role=ally），可以有一个见证主角翻身的旁观者（role=witness）。
  每人写 id（如 char-1）、name、public_face（别人眼里的他）、want、stake（会失去什么）。
  主角写 edge：他的金手指或底牌，规则简单、一句话能说清，有边界或代价，能在第一到三章用上。
  来历只许两种，可以反复叠用。一是奇遇：高人、残识或遗物把一门本事塞给他，他自己不会凭空生出来。
  二是残方：他捡到或看懂一页被丢掉的法门，会的是这一式，不是整个人升级。
  开局就是满级武力要少用。修为已经到顶，后面就很难再拿修炼做矛盾。
  挂只补他算到的那一步，不替他赢，也不能自己变强。他得有计谋：挑、瞒、将计就计、拿对方的规矩做局。没有这层，这本打回。
  反派要分层：眼前踩主角的人、他背后更强的人、远处的大目标。
  反派写 surface_motive：他凭什么看不起主角、他想要什么。
  反派不能降智：他欺负主角是因为有底气，输是因为不知道主角的底牌，不是因为蠢。""",
    "architect.why": """\
- core：核心体验，一句话。读者每章回来追的那种爽，要具体到情绪，
  例如“被所有人当成废物，却一次次当着他们的面扳回一城的痛快”
  或“一路往上爬，把曾经够不着的人一个个甩在身后的扬眉吐气”。全书每一章都要喂这种感觉。
- themes：一到三个主题。每个写 id（T-1…）、question（主题追问，写成问题，
  例如“被踩过的人翻身以后，要不要也去踩别人？”）、tension（两种都有道理的回答，人物会站在不同的一边）、
  arc（三到五步，主角对这个问题的回答怎样随故事变化：起点、动摇、代价、新的回答）。
  主题长在主角翻身的路上：他凭什么赢、赢了以后成了什么样的人。爽归爽，不说教。
- approach：写作思路。
  engine：叙事引擎，每章重复并升级的阅读动力，例如“每章有人看轻他，他用底牌当场打脸，
  换来更大的舞台和更强的对手”。
  voice：叙述声音，例如“贴着主角的近距离第三人称，嘴上不饶人，心里记账，出手干脆”。
  motifs：两到四个反复出现的意象或物件，每次出现意义都往前走一步（例如一句被嘲笑过的话、一件旧物）。
  principles：两到四条这本书的写法原则（例如“先压后放，压要具体，放要写足反应”）。""",
    "architect.secret_count": "0 到 2 个秘密（可以没有）",
    "architect.secrets": """\
- 读者第一章就要看懂底牌怎么用、边界在哪，只是对手不知道。来历可以后揭，但第一章得先埋看得见的头：一枚不一样的东西、半页残方、一句没说完的话。
- 禁止废材吃了废材就崛起，却不写这口力是谁留下的、为什么只在这一步管用。
- 秘密只放长线（这挂是谁留下的、幕后是谁）。没有长线就让 secrets 和 reveal_plan 为空。
- 金手指要有边界和代价。每一次变强都要对应一次奇遇或一张残方，再加他自己的取舍，不能平白升级。""",
    "plausibility": """你是爽文网文的资深审稿人。检查下面的 Canon。

- plausible：金手指有没有来历、边界和代价；每一次变强能不能对上一次奇遇或一张残方。反派的行为有没有动机和底气。
- fair_play：爽点是不是主角的计谋在用这挂（他事先看到了什么、做了哪一步），挂只补那一步。
  不许靠巧合、天降援兵、对手犯蠢，也不许底牌自己生效、自己升级。
- problems：列出最严重的问题，每条一句话。没有就留空。

Canon：
{canon}""",
    "themes.identity": "这本爽文网文的主编",
    "themes.core": (
        "  说清楚爽在哪里：是被看不起后一次次扳回一城，是一路升级把曾经够不着的人甩在身后，"
        "还是护住自己人的痛快。"
    ),
    "themes.guard": "  主题长在主角翻身的路上：他凭什么赢、赢了以后成了什么样的人。不要写成说教。",
    "planner.identity": "网文爽文的总编剧",
    "planner.mission": (
        "你的工作是把主角的翻身路拆成一章一章的爽点：每章先压后放，压要具体，放要痛快，"
        "而写手只看到可见的事。"
    ),
    "planner.stakes": "实力、地位、资源、对手的态度、旁人的眼光",
    "planner.beats": """\
  要有压抑：先让读者看见主角被看轻、被逼到墙角，或一件他非做成不可的事，读者要跟着憋一口气。
  要有爆发：主角用 edge 出手，对手以为稳赢、旁观者以为他完了的局面当场翻过来。
  要有反应和收获：写对手和旁观者怎么变脸、改口，主角拿到了什么。
  可以写主角的盘算和底气、对手的嚣张、旁观者的议论；蓄力章把压力垒高，最后一拍让读者知道快出手了。
  爆发必须先写他的计：他看到了哪一个漏洞，做了哪一步手脚，底牌只补了这一步。""",
    "planner.craft": """\
- plants：伏笔，零到两条。主角的底牌、对手的软肋或后面要兑现的承诺，先在这一章露一个看得见的头，
  后面打脸时能对上。只写看得见的东西，不要写它意味着什么。
- misdirection：误导，零到一条。可见的细节，让对手和旁观者低估主角。不能撒谎。
- 爽点节奏：每一到两章至少兑现一次小爽点，每三到五章一次大爽点（当众打脸、越级取胜、身份揭晓）；
  主角受气不能连续超过一章不还手。
- 上一章结尾的那件事，就是下一章开头要处理的事。底牌不能自己升级。""",
    "planner.no_spoil": "说出长线悬念的答案",
    "planner.opening": """\
- sc-01 入局：三百字内主角已经陷在最糟的处境里（被退婚、被开除、被当众羞辱、被逼到绝路），
  本章前半金手指或底牌出现。先让读者认识主角：他是谁、受着什么气、最想要什么；被踩得越具体，翻身越爽。
- sc-02 加压：对手加码，主角第一次用 edge 小小还手，尝到甜头，也惹来更大的麻烦。
- sc-03 承诺：第一次当众打脸，兑现前两章的憋屈，再亮出更大的目标或更强的对手，给出全书的追读理由。
钩子要一章比一章大：对手更强，赌注更高，舞台更大。""",
    "writer.identity": "成熟的网文爽文作者",
    "writer.craft": """\
- scene.plants 是伏笔：主角的底牌或对手的软肋先露个头，自然地放进场景里，不要解释。
- scene.misdirection 是让人低估主角的可见细节：写出来，让对手和旁观者看走眼。
- 爽点要写足：出手前给一拍停顿，出手写动作和结果，再写对手的脸色和旁观者的反应，最后落到主角拿到了什么。
  不要一句“他轻松赢了”带过，不要靠旁白宣布主角有多强。
- 主角不圣母：受了气要记账，有能力还手时就还手。反派不降智：他嚣张有底气，输在不知道主角的底牌。
- 底牌出场要让读者看见因果：他先做了什么，这一下才成立。章与章之间接住上一章的钩子。""",
    "writer.opening": """\
- “入局”：三百字内主角已经在受气或陷入绝境，本章前半金手指或底牌出现；
  先让读者认识主角的处境，跟着他憋住这口气。
- “加压”：对手加码，主角第一次小小还手，尝到甜头，也惹来更大的麻烦。
- “承诺”：第一次当众打脸，写足对手和旁观者的反应，再亮出更大的目标。""",
    "critic.identity": "在番茄和起点追爽文的老读者，也是挑剔的编辑",
    "critic.craft": (
        "- 爽点有没有落地：主角怎么出手、对手怎么变脸、旁观者怎么改口、主角拿到了什么；"
        "反派有没有降智，主角有没有圣母或受气太久。"
    ),
    "critic.setup": "- 出手前的压抑够不够：对手的轻视和主角的处境有没有让你憋住一口气，而不是一上来就赢。",
    "reviser.leak": "- 若问题是泄底：删掉把底牌来历或长线说破的句子，改回一个看得见的动作。已经用掉的东西不要写回来。",
    "reviser.hint": "- 若问题是铺垫没落地：留下一个看得见的细节，不要解释它以后有什么用。",
    "reviser.skim": "- 若问题含 skip rate，或段落太长：压缩想跳过的段落，删掉重复，保留这一章的压抑、出手和旁人的反应。",
    "judge.identity": "网文爽文的判卷人",
    "judge.examples": "身世、幕后的人是谁、金手指的来历",
    "baseline.kind": "爽文短篇",
}

# Open hot, then a wave: build-up, payoff, a breath, a bigger payoff.
KNOTS: tuple[tuple[float, float], ...] = (
    (0.0, 0.75),
    (0.2, 0.85),
    (0.3, 0.6),
    (0.5, 0.88),
    (0.6, 0.65),
    (0.8, 0.92),
    (0.88, 0.7),
    (1.0, 0.97),
)

LENGTH_BUDGET: dict[str, int] = {
    "slack": 2600,
    "steady": 2400,
    "tight": 2200,
    "sprint": 2000,
}

PACE_CRAFT: dict[str, str] = {
    "slack": (
        "节奏是 slack。这是蓄力章：把压力和期待一层层垒起来，对手的轻视、旁人的嘲笑、主角心里那笔账；"
        "可以写日常和关系，但每一段都要让读者更想看主角出手。"
    ),
    "steady": (
        "节奏是 steady。叙述、对话和主角的盘算交替推进；一边铺下一个爽点，一边兑现一个小的。"
        "不要停下来讲设定。"
    ),
    "tight": (
        "节奏是 tight。冲突当面摊开，句子偏短；主角的判断和出手要快，对手的反应要写出来。"
        "设定和回忆一笔带过。"
    ),
    "sprint": (
        "节奏是 sprint。爆发章：主角出手、对手崩盘、旁观者震动，短句短段，动作和对话为主；"
        "高光那几句给足画面，不要一句话带过。"
    ),
}

EDGE_AUDIT = """你在验收爽文的金手指。只看 Canon 的公开层，尤其是主角的 edge。

problems 里逐条写失败的原因，没有就留空：
- 没有来历：看不出这口力是奇遇所赠（残识、高人、遗物），还是他捡到并看懂的残方。
- 开局满级：修为已经到顶，后面没法再拿修炼做矛盾。
- 没有边界或代价：看不出它不能做什么、用一次会失去什么。
- 凭空变强：没有写清为什么是他、为什么只在这一步管用。
- 没有计谋：赢只靠底牌自动生效，看不到他的挑选、隐瞒或将计就计。

Canon：
{canon}"""

CARD_AUDIT = """你在验收爽文的场景卡。对照 Canon。

problems 里逐条写，注明场次，没有就留空：
- 从第二场起，开头没有在处理上一场结尾的那件事。
- 某一场多出来的本事，对不上一次奇遇、一张残方或主角的一次取舍。
- 爽点不是主角做了手脚，只是底牌自己生效。
- 底牌跨场变强，却没有新的残方，也没有新的代价。

Canon：
{canon}

场景卡：
{cards}"""

SHUANGWEN = Genre(
    id="shuangwen",
    name="爽文",
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
        ("payoff", "advisory"),
        ("hint", "advisory"),
        ("tension", "advisory"),
        ("skim", "advisory"),
        ("hooks", "advisory"),
        ("retention", "advisory"),
    ),
    knots=KNOTS,
    length_budget=LENGTH_BUDGET,
    pace_craft=PACE_CRAFT,
    personas=Path(__file__).with_name("shuangwen.yaml"),
    requires_secrets=False,
    required_roles={"protagonist": "主角", "antagonist": "反派"},
    beat_fields={
        "face_slap": "打脸。谁看轻或逼迫主角，主角用什么当场让他付出代价；蓄力章写谁在压主角、这笔账记在哪",
        "gain": "收获。这一章主角实打实拿到的东西（实力、钱、地位、人、信息），具体到能数",
        "reaction": "反应。对手和旁观者怎么看、怎么改口，态度怎样翻过来",
        "spent": "用掉。这一章消耗掉、下一章不能再当成还在手里的东西，具体到能对上之前拿到的",
    },
    inference_tolerance=1,
    ledger_gain="gain",
    ledger_spent="spent",
    audit_edge=EDGE_AUDIT,
    audit_cards=CARD_AUDIT,
    require_story=True,
)
