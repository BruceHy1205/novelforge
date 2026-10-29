# NovelForge

源码现托管于 GitHub：[BruceHy1205/novelforge](https://github.com/BruceHy1205/novelforge)。

读者认知驱动的 AI 长篇小说生产。

AI 写小说常见两种无聊：**进展慢**（原地铺陈、反复描写）和**像说明文一样剧透**（忍不住解释真相）。两者的共同根源是写手模型知道答案、却不知道读者此刻知道什么。NovelForge 的做法是：

- **Canon（作者全知）与写手视图分离**：写手看不到秘密原文，只拿到“只有表现、没有原因”的行为指令。
- **写后验收**：由程序闸门 + 只看正文的**读者模拟器**判断“读者猜到了没有、想不想跳过”，不过就修订或退回规划。

同一 Story Core 日后与 GalFactory 矩阵对接；当前只做小说管线，不做 VN export。

当前阶段：**P0–P5 的代码已落地**。`plan` / `write` 覆盖节奏、行为指令、线索、文风和长篇记忆。读者模拟器读章节摘要加最近三场全文。`gates` 统计哪个闸门失败最多。真人问卷、盲测和人审节点按指令跳过，不会停下来等人。详细计划见 [`docs/PLAN.md`](docs/PLAN.md)。

## 快速开始

```bash
uv sync
uv run pytest                  # 全部离线，零网络
uv run ruff check . && uv run ruff format --check .
uv run novelforge init demo    # 生成 projects/demo/{canon.yaml,models.yaml,scenes/,manuscript/}
uv run novelforge version
uv run novelforge doctor
```

写一部短篇（`--fake` 不调模型，正式运行去掉它；需要环境变量 `ark_plan_api_key`）：

```bash
uv run novelforge init demo
uv run novelforge plan demo "渡口封了，账房连夜离开" --scenes 8
uv run novelforge write demo          # manuscript/book.md，可从 checkpoints.sqlite 续跑
uv run novelforge write demo --limit 2 --drafts 2         # 只写前两章；每章两份候选，评审挑一份
uv run novelforge baseline demo "渡口封了，账房连夜离开"   # 对照组，一次写完
uv run novelforge rollback_scene demo sc-03              # 撤掉 sc-03 及之后，再 write 续写
uv run novelforge gates demo                             # 闸门失败次数，以及先改哪条提示词
uv run novelforge genres                                 # 列出题材规则集
uv run novelforge init demo --genre mystery              # 题材写进 projects/demo/project.yaml
uv run novelforge init zhang --genre shuangwen           # 爽文项目；之后 plan / write 自动按爽文跑
```

批量生产台（默认暂停，点「开始生产」才跑）：

```bash
uv sync
cd web && npm install && npm run build    # 前端写到 novelforge/web/static
uv run novelforge serve                   # 默认 http://127.0.0.1:8765 ，状态库和书都在 ./factory/
```

`--root` 换工厂目录，`--host` / `--port` 改地址。先在设置里打开「演练模式」可以不调模型走通流程。正式跑关掉演练模式，并设置 `ark_plan_api_key`。

生产按阶段走：大纲 → 试读（默认 5 章，可改）→ 全书。大纲审核、试读审核各自可以开关；开着就停在对应审核页，通过后优先续写，关着就自动进入下一阶段。三项上限防止堆书：总体未完成（默认 50）、大纲积压（生成中 + 待审 + 待写试读）、试读积压（生成中 + 待审 + 待续写全书）。任一阶段都可以毙掉，书进回收站，默认 30 天后删除，也可以恢复。题材在「题材批次」里设规则集、核心内容、每行一条的具体创意、本数和每本章数。

题材在 `init --genre` 或 `plan --genre` 时写进 `project.yaml`，之后 `plan` / `write` / `baseline` 都按它跑；没有 `project.yaml` 就是悬疑 `mystery`。内置两套：

| 题材 | id | 核心循环 | 和悬疑不同的地方 |
| --- | --- | --- | --- |
| 悬疑推理 | `mystery` | 藏真相、埋线索、读者猜 | 原有规则，提示词逐字不变 |
| 爽文 | `shuangwen` | 先压后放：受气、蓄力、当众打脸、拿到收获、换更大的舞台 | 秘密可以没有（金手指不是秘密，读者第一章就知道，只是对手不知道）；人物是主角加分层反派（`antagonist`），反派不许降智；场景卡多三条专属节拍 `face_slap` / `gain` / `reaction`；多一道提示级闸门 `payoff`（小模型只读正文和公开卡片，判断爽点有没有落地，指出哪段一句话带过、靠旁白吹、圣母或憋屈太久）；张力曲线是一波一波的（蓄力、爆发、喘口气、更大的爆发），篇幅 2000–2600 字；金手指要有来历：奇遇所赠，或捡到的残方，开局满级少用；读者第一章看懂用法和边界，来历可以后揭；每次变强对得上一次奇遇或一张残方，爽点是主角的计谋在用这挂，挂不自己升级。架构审稿查这些，也查爽点是不是主角挣来的；读者画像换成番茄爽文老读者、起点老白、通勤摸鱼党 |

`--path` 指定工作区根目录。`--scenes` 默认 8。`--scenes-per-batch` 默认 3，是每次规划调用写几张场景卡；思考模型输出顶满时可以改成 1。一场就是一章网文。`pace` 四档的篇幅预算是 slack 2800、steady 2600、tight 2400、sprint 2200 个汉字，写手提示会跟着档位换节奏。张力曲线从 0.66 起步。跳读达到 15% 会把这一场收紧一档再改。连续两场张力偏低，下一场改成 sprint；连续偏高，下一场改成 slack。

闸门分两级。拦截级（G1 字面泄底、G2 视角越界、指令泄底、G5 推断泄底、G6 揭示越权）不过时，同一场最多修订 2 轮，然后重规划 1 次，仍不过就停在该场并报错。G5 允许读者比计划早一档起疑，但揭示前不允许“确定”。提示级（G3 篇幅、节奏形状、G4 文风、G7 暗示、G8 张力、G9 跳读、G10 钩子、G11 追读）不过时只触发 1 轮修订，之后带着记录锁定，结果仍计入 `novelforge gates`。

校准相关命令（离线试跑用 `--fake`，正式运行去掉它）：

```bash
D=novelforge/eval/calibration/example
uv run novelforge eval questionnaire $D/story.yaml --reader r01
uv run novelforge eval contamination $D/story.yaml --fake
uv run novelforge eval calibrate $D/story.yaml --responses $D/responses --fake --repeats 2
```

模型默认走火山引擎 Ark agent plan（`https://ark.cn-beijing.volces.com/api/plan/v3`），需要设置环境变量 `ark_plan_api_key`：

| 角色 | 默认模型 |
| --- | --- |
| architect、planner、critic | `kimi-k2.8-preview`（思考模型，推理开启，输出上限 65536；规划器默认每次写三章，可用 `--scenes-per-batch` 调整） |
| writer、reader_sim、reviser、gate | `deepseek-v4.1-flash`（关闭推理） |

`models.yaml` 可以按角色改模型，`models` 段可以按模型覆盖 `timeout`、`max_tokens`、`disable_thinking`，也可以在 `provider` 里换成其他 OpenAI 兼容接口。结构化输出默认用 Instructor 的 JSON 模式，因为 `kimi-k3` 不接受工具调用模式。设置 `LANGFUSE_PUBLIC_KEY` 和 `LANGFUSE_SECRET_KEY` 后，每次模型调用会记录到 Langfuse；不设置则静默跳过。

## 技术框架

### 技术栈

| 层 | 选型 | 用途 |
| --- | --- | --- |
| 语言 | Python 3.12 + uv | 大模型生态最全；uv 锁依赖 |
| 编排 | LangGraph | 场景流水线状态图：循环、条件分支、检查点、人审中断 |
| 数据模型 | Pydantic v2 | Canon、读者状态、场景卡、闸门结果全部类型化 |
| 模型接入 | LiteLLM | 统一接口，按角色配置不同模型 |
| 结构化输出 | Instructor | 读者模拟器和闸门的输出直接解析成 Pydantic 对象 |
| 持久化 | LangGraph SqliteSaver + YAML | 运行状态存 SQLite，可按场景回滚；Canon 和场景卡存 YAML，方便人工编辑 |
| 语义匹配 | 汉字二元组 | G1 近似泄底。bge-m3 未接入，测试不下载模型 |
| 观测与评估 | Langfuse | 追踪每次调用；用数据集和实验功能做回归评估（无 key 时 no-op） |
| 命令行 | Typer | `init`、`plan`、`write`、`eval` 等命令 |
| 测试 | pytest + 假模型客户端 | 单测不调用真实模型 |

暂不做：向量数据库（状态账本是结构化数据，不需要检索）、多 agent 对话框架。批量生产台在 `web/`，由 `novelforge serve` 提供。

### 角色

| 角色 | 输入 | 输出 |
| --- | --- | --- |
| 架构师 architect | 一段创意 | 先出 3 个开书方案，由读者画像按“会不会点开”打分选一个；再写 Canon：公开的故事层（卖点、主角和他的优势、3–5 个嫌疑人、主期待和支线期待）、这本书为什么而写（核心体验 `core`、一到三个主题 `themes`、写作思路 `approach`：叙事引擎、叙述声音、反复意象、写法原则）加真相、秘密、揭示计划；最后由 `gate` 检查手法是否现实可行、推理是否公平，不过就带着问题重写一次 |
| 规划器 planner | Canon + 当前读者状态 | 每章一张场景卡：起承转合 `beats`、伏笔 `plants`、误导 `misdirection`（规划器知道真相，但只写可见细节）、期待 / 压抑 / 释放（`reader_want`、`obstacle`、`payoff`、`state_change`）、主题落点 `theme_beat` 和本章读者感受 `reader_feeling`、黄金三章任务（入局、加压、承诺）、最多四条必须发生的事件、必须揭示/隐瞒、暗示预算。视角默认是主角 |
| 视图过滤器 view | BookState + 场景卡 | WriterView（纯代码白名单，不调模型） |
| 写手 writer | **只有** WriterView | 一整章正文：铺垫、氛围、对话潜台词、主角的回忆和内心都可以写 |
| 评审 critic | **只有**上一章结尾 + 同一章的候选稿 + 由公开故事层生成的写作纲领 | 选出更想追读的一份，给出修改意见（含前后矛盾），判断主题落点有没有落地，并写下这一章主题实际走到了哪里（`theme_notes`，下一章写手会看到） |
| 读者模拟器 reader_sim | **只有**已锁定正文（更早的章是摘要，最近三场是全文）+ 读者画像 + 不含答案的探针问题 | ReaderReport：每个问题的猜测和信心、最想知道什么、想跳过哪段、张力、会不会点下一章和原因、最想看主角做成什么、最想放下书的段落 |
| 猜测判定 | ReaderReport + Canon | 把猜测对应回秘密，更新读者状态（P1） |
| 修订者 reviser | WriterView + 当前正文 + 不含秘密原文的违规原因 | 文风和 POV 只改违规段；篇幅、节奏、钩子、泄底整场重写 |

### 两条宪法（写进代码，不靠约定）

1. **写手视图用白名单构造，不在完整状态上做删减。** `WriterView` 设 `extra="forbid"`，只能由 `build_writer_view(BookState, SceneCard)` 构造。写手拿到的读者状态和 POV 状态是公开投影，不含秘密 ID 和信心值；也看不到 `must_withhold`、`hint_budget`。单测把所有未揭示秘密的原文和 ID 序列化，断言它们不出现在 `WriterView` 的 JSON 里；失败不可合并。秘密已揭示、或由本场 `must_reveal` 揭示时才解锁。
2. **读者模拟器只读已锁定的正文。** `simulate_reader(manuscript: list[LockedScene], persona, probes)` 的签名里不接收 Canon、场景卡或 BookState；单测检查参数名和类型。探针问题由 `probes_from_canon` 生成，含答案的问题会被拒绝。

原文子串测试是必要条件，不是充分条件。行为指令可以换个说法泄露真相。规划器写出的因果从句会先被砍掉，只留可见动作；读者模拟器再只读指令文本，猜到 `suspect` / `certain` 就重写一次，仍泄露则丢掉指令。主闸门里同一条检查会再跑一遍。

### 闸门

| 编号 | 模块 | 检查 | 实现方式 | 计划阶段 |
| --- | --- | --- | --- | --- |
| G1 | `gates/literal.py` | 字面泄底 | 子串 + 汉字二元组 | 已实现（bge-m3 未接入） |
| G2 | `gates/pov.py` | POV 越界 | 代码 | 已实现 |
| G3 | `gates/length.py` | 篇幅 | 代码 | 已实现 |
| G4 | `gates/style.py` | 禁用句式、照抄文风示例 | 代码 + 清单 | 已实现 |
| G5 | `gates/inference.py` | 推断式泄底 | 读者模拟器 + 线索累计 | 已实现 |
| G6 | `gates/inference.py` | 揭示越权 | 读者模拟器 + 揭示计划 | 已实现 |
| G7 | `gates/hint.py` | 暗示失效、过猛、没带下去、没埋线索 | 读者模拟器 + 线索账本 | 已实现 |
| G8 | `gates/tension.py` | 张力 | 读者模拟器 | 已实现 |
| G9 | `gates/skim.py` | 拖沓 | 跳读段落占比 ≥ 15% | 已实现 |
| G10 | `gates/hooks.py` | 空转钩子 | 结尾钩子、回应、读者问题是否还在 | 已实现 |
| 爽 | `gates/payoff.py` | 爽点落地（仅 `shuangwen`） | 小模型读正文和公开卡片 | 已实现 |
| G11 | `gates/retention.py` | 追读 | 前三场有一位读者不点下一章就不过；之后过半不点才不过。修订者会拿到去掉秘密原文的读者原话 | 已实现 |

闸门分层：先跑便宜的代码闸门（pre_gates：G1、G2、G3、pace 形状、G4，以及不调模型的因果指令检查）。这些不过，就不跑读者模拟器。指令换说法泄露改由小模型 `gate` 检查。过了初筛才跑读者模拟器，然后是 G5–G11。

主题怎么用：核心体验是每章都要喂的那种感觉；主题写成问题，`arc` 是主角的回答怎样变化；每章的 `theme_beat` 是主角在主题上走的那一步，必须落成一个选择或代价，不写感悟、不说教。主题是“可以变”的：评审每锁定一章就记下主题实际走到哪里，下一章从那里接着写，可以推进、动摇或翻转。主题也是公开文本，所以和伏笔一样要过泄露检查：盲读者能从某个主题猜出秘密，这个主题就被丢掉。旧 Canon 没有主题时，`plan --keep-canon` 会在原 Canon 上补写。评审判断主题没落地时触发一次建议性修订（`theme`）。

故事层（`Canon.story`）、场景卡的三拍字段和 `beats` / `plants` / `misdirection` 都是公开的，会进入写手视图；视图过滤器同样检查它们，不能夹带秘密原文。伏笔和误导与指令一起交给小模型做换说法泄露检查，泄露就先重写，再丢伏笔，最后丢指令。写手可以写视角人物自己的判断、恐惧和打算，G2 只拦别人的内心和视角人物不该知道的事。`models.yaml` 的 `provider.disable_thinking: true` 会关闭推理，避免推理吃掉输出上限、把 JSON 截断。

### 题材规则集

引擎只有一套：单场状态图、整书循环、写手视图白名单、读者模拟器签名、长篇记忆、模型路由、评审和主题层，所有题材共用。题材（`novelforge/genres/`）是挂在引擎上的一份规则：

| 题材提供 | 字段 | 作用 |
| --- | --- | --- |
| 提示词插槽 | `prompts` | 各角色模板里的 `<<identity>>`、`<<craft>>` 等槽位，例如身份、人物配置、秘密写法、伏笔要求、评审标准；一个都不能缺 |
| 闸门清单与分级 | `pre_gates` / `main_gates` | 每一项是 `(闸门 id, blocking 或 advisory)`；闸门统一注册在 `gates/registry.py`，可以加题材自己的闸门 |
| Canon 要求 | `requires_secrets`、`required_roles` | 是否必须有秘密、必须有哪些角色（`Character.role` 是自由文本） |
| 专属节拍 | `beat_fields` | 场景卡 `genre_beats` 的键，例如怪谈的“本章规则”；和伏笔一样进写手视图、过泄露检查 |
| 节奏 | `knots`、`length_budget`、`pace_craft` | 张力曲线、四档篇幅、各档写法 |
| 读者画像 | `personas` | 读者模拟器用的画像文件 |

宪法不随题材变：四个泄底闸门（literal、directive、inference、reveal）在每个题材里都必须是拦截级，`Genre` 构造时就会检查；没有秘密的题材里它们直接通过。`tests/test_genre_snapshot.py` 锁住悬疑题材发出的全部提示词，重构不能让它们变一个字；确需改提示词时，运行 `uv run python tests/prompt_capture.py` 并审 diff。

加一个题材：在 `novelforge/genres/` 新建模块，用 `Genre(...)`（或 `dataclasses.replace(MYSTERY, ...)`）填好插槽和清单，在 `genres/__init__.py` 里注册，再补一份 `personas` 和测试。

规划阶段的验收按题材开关，不写进正文之前。爽文开着三道：`audit_edge` 退回没有来历、开局满级、没有边界或没有计谋的金手指；`audit_cards` 加上衔接检查，退回接不上上一场钩子、缺专属节拍、本事自己长出来的场景卡；`require_story` 在已有主题但核心体验或叙事引擎空着时只补空缺，不覆盖已经写好的主题。悬疑这三道都关着，发出的提示词保持原样。退回只重写一次。第二次仍不过就抛出 `PlanRejected`，这一轮不保存：金手指验收不过时不写 `canon.yaml`，场景卡验收不过时不写 `scenes/sc-*.yaml`。`novelforge plan` 这时退出码是 1。

修订者的泄底、铺垫和跳读三句是题材槽位（`reviser.leak`、`reviser.hint`、`reviser.skim`）。爽文另有一本账：锁定一章时，`genre_beats` 里的 `gain` 记入 `ledger_have`，`spent` 记入 `ledger_spent` 并从手里划掉。下一章的写手看得到这两份清单，用掉的不能再写成还在手里。

### 单场状态图

```
plan_scene → build_view → write → pre_gates ─不过→ revise ─┐
                                     │过                   │（不超过 2 轮）
                                     ▼                     │
                               reader_sim → main_gates ─不过→ revise
                                                 │过        │超过轮数
                                                 ▼          ▼
                                           update_state   replan_scene
                                                 │
                                                 ▼
                                            lock_scene
```

每个节点是纯函数：读入状态，返回更新后的状态。图只负责路由，所以每个节点可以单独测。读者状态由读者模拟器更新，不由规划器假设。

### 目录

```
novelforge/
  schema/        canon.py story.py clues.py reader.py scene.py gate.py
  roles/         architect.py themes.py planner.py writer.py critic.py reviser.py directives.py behavior.py clues.py memory.py reader_sim.py
  view/          filter.py          # 纯代码白名单
  genres/        base.py mystery.py shuangwen.py # 题材规则集：提示词插槽、闸门清单、节奏、画像
  gates/         registry.py builtin.py literal.py pov.py length.py pace.py style.py behavior.py inference.py hint.py tension.py skim.py hooks.py retention.py
  pacing/        curve.py pace.py   # 张力曲线、篇幅预算、中观纠偏
  graph/         scene_graph.py book_graph.py checkpoint.py
  pipeline.py    plan / write / baseline / rollback
  store.py       canon、场景卡、state.yaml、快照、成稿
  llm/           client.py fake.py  # LiteLLM + Instructor，按角色路由；测试用假客户端
  eval/          calibration/ metrics.py
  factory/       批量生产台：题材批次、阶段队列、审核、回收站
  web/           serve 用的 HTTP API（静态页来自仓库根的 web/）
  cli.py
web/             Vue 3 控制台；npm run build 写入 novelforge/web/static
projects/<作品名>/  project.yaml canon.yaml scenes/ manuscript/
tests/
docs/PLAN.md
```

## 开发路线

| 阶段 | 目标 | 状态 |
| --- | --- | --- |
| P0 基建 | 数据模型、视图隔离、模型封装、CLI 骨架、单场状态图路由 | 已完成 |
| P1 读者模拟器校准 | 模拟器信心与真人基准对齐 | 工具完成；真人问卷已跳过 |
| P2 最小闭环 | 端到端生成悬疑短篇 | 代码完成；真人验收已跳过 |
| P3 节奏控制 | pace 档位、拖沓与空转钩子、张力曲线纠偏 | 代码完成；真人对照已跳过 |
| P4 写作质量 | 行为指令层、线索账本、POV、文风、定点修订 | 代码完成；真人对照已跳过 |
| P5 长篇化 | 章节摘要、摘要式读者输入、成本分层、闸门频率 | 代码完成；人审与重新校准已跳过 |

每阶段的交付和任务拆分见 [`docs/PLAN.md`](docs/PLAN.md)。代码侧的计划到 P5 结束。bge-m3 仍不接入。

## 许可

MIT
