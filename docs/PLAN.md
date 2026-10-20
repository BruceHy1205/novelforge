# NovelForge 开发计划

技术框架见 [`README.md`](../README.md)。本文件是阶段计划和任务清单，按依赖排序。

## 总原则

1. **先校准读者模拟器，再搭流水线。** 读者模拟器判断“读者猜到了没有、想不想跳过”，是全部闸门的地基。地基不准，后面全部白做。
2. **每个阶段有退出标准，达不到不进入下一阶段。** 达不到时按该阶段的“退路”处理。
3. **写手和规划器已经按指令落地。** 真人校准结果不再挡住代码。不要停下来请人审阅猜测或问卷。
4. **单测永远离线。** 真实模型调用只出现在命令行里，不出现在 pytest 里。
5. **需要真人的退出标准整段跳过。** 校准故事和 `REVIEW.md` 只作为程序试跑材料，不作为待办。

任务标记：`[x]` 已完成，`[ ]` 待做，`[人]` 需要人力、不能靠写代码推进。

---

## P0 基建（已完成）

**目标**：数据模型、视图隔离、模型封装、CLI 骨架，作为整套方案的“宪法”。

### 已完成

- [x] uv 项目、`novelforge` 包、MIT 许可
- [x] Pydantic 模型：`Canon`、`Secret`、`RevealPlanItem`、`Clue`、`ReaderState`、`POVState`、`SceneCard`、`PublicSceneCard`、`WriterView`、`GateResult`、`ReaderReport`、`ReaderPersona`
- [x] `build_writer_view` 白名单过滤 + 隔离单测（每个秘密字段注入独立标记，断言不出现在 WriterView JSON 中）
- [x] `simulate_reader` 签名单测（不含 Canon / SceneCard）
- [x] LiteLLM + Instructor 封装、确定性 `FakeLLMClient`
- [x] Langfuse 无 key 时 no-op
- [x] Typer CLI：`init` / `version` / `doctor`
- [x] 角色、闸门、图、节奏模块的 stub；校准问卷模板
- [x] pytest 全局禁网

### 对齐（已完成）

- [x] 从写手视图移除 `withhold_ids` 和 `hint_budget`；`PublicSceneCard` 也不再含 `must_reveal` / `must_withhold` / `hint_budget`
- [x] `WriterView` 字段：`scene`、`reader_state`、`pov_state`、`directives`、`prev_tail`、`style_samples`
- [x] 新增 `BookState`；`build_writer_view(state: BookState, card: SceneCard)`
- [x] 新增 `LockedScene`（不可变，带 sha256）；`simulate_reader(manuscript: list[LockedScene], persona: Persona, probes)`
- [x] `ReaderReport`：`guesses`（每个探针问题的猜测 + 信心粗档）、`wants_to_know`、`skip_spans`、`tension`
- [x] 隔离测试扩展：秘密原文和**未揭示的秘密 ID** 都不得出现在写手视图；作者填写的字段含秘密时报错，模拟器产生的读者问题含秘密时丢弃
- [x] 按角色路由模型：`projects/<name>/models.yaml`
- [x] Langfuse v5 接进 `LiteLLMClient.complete`：记录角色、场景 ID、token、成本、错误；无 key 静默
- [x] `init` 同时创建 `models.yaml`、`scenes/`、`manuscript/`
- [x] 单场状态图全部节点和条件边；路由逐边测试（修订上限 2 轮 → 重新规划 1 次 → 升级人审）
- [x] ruff 静态检查与格式化；在无网络命名空间中验证 pytest 通过

### 对齐中做出的设计决定

1. **写手看到的是公开投影，不是原始状态。** 计划里写的是 `reader_state: ReaderState`、`pov_state: POVState`，但这两个模型里有秘密 ID 和每个秘密的信心值。实现改为 `PublicReaderState`（只有读者正在问的问题）和 `PublicPOVState`（位置、情绪、目标），原始状态只留在 `BookState` 里。
2. **读者模拟器通过“探针问题”报告信心。** 模拟器不见 Canon，就没法直接说“对秘密 S-001 的信心”。做法是每个秘密配一条不含答案的公开问题（`Secret.probe_question`，如“谁是凶手？”），模拟器回答猜测和信心；另一个能看 Canon 的判定步骤再把猜测对应回秘密，更新 `ReaderState.secret_confidence`。判定步骤在 P1 实现。`probes_from_canon` 会拒绝含答案的问题。
3. **揭示场景可以解锁秘密。** 秘密一旦在 `BookState.revealed_secret_ids` 里，或出现在本场 `must_reveal` 中，它的原文就可以进入写手视图；否则 payoff 场景无法写。其余秘密的隔离规则不变。

### 退出标准

- `uv sync && uv run pytest` 全部通过，不依赖网络
- 视图隔离测试覆盖所有秘密字段，包括新增的 `reader_state` / `pov_state`
- 单场状态图的路由测试覆盖每条边

---

## P1 读者模拟器校准（最关键）

**目标**：证明读者模拟器对“读者猜到了没有”的判断和真人一致。这决定整套方案能不能成立。

使用说明见 [`novelforge/eval/calibration/README.md`](../novelforge/eval/calibration/README.md)。

### 代码任务

- [x] 猜测判定（`roles/guess_judge.py`）：关键词判卷和模型判卷，把猜测判为 wrong / partial / correct；真人和模拟器用同一个判卷人。问卷里可由整理人直接标 `correct` 覆盖判卷
- [x] 校准数据结构（`eval/calibration/schema.py`）：`CalibrationStory`（含 `renamed`、`ai_generated`）、`CalibrationScene`、`CalibrationSecret`（探针问题、真相、关键词、`revealed_in`）、`HumanResponseSet` / `SceneResponse` / `HumanGuess`
- [x] 问卷：`novelforge eval questionnaire` 按故事生成预填好的问卷；静态模板附填写说明
- [x] 读者画像配置：`eval/calibration/personas.yaml`（推理迷、普通读者、没耐心的读者），`--personas` 可替换
- [x] 读者模拟器第一版提示词（`reader-sim-v1`）：逐场输入、段落编号、四档信心定义、输出清洗
- [x] 校准脚本 `novelforge eval calibrate`：每个画像和集成的 Spearman、真人分半上限、漏报率、误报率、跳读重叠、每个秘密的“真人何时猜到 / 模拟器何时猜到”，并按退出标准给出 PASS / FAIL；完整结果可存为 JSON
- [x] 污染检查 `novelforge eval contamination`：只给标题和出处问探针问题，答对即标记
- [x] 合成示例故事和合成问卷（`eval/calibration/example/`），用于演示格式和测试，**不是真实数据**
- [x] 接入火山引擎 Ark agent plan（`kimi-k3`、`deepseek-v4-pro`、`deepseek-v4.1-flash`），用真实模型在示例故事上跑通污染检查和完整校准
- [x] 探针提问窗口 `ask_from`：真实运行中发现“人物还没出场就问他和死者的关系”会让问题本身泄露信息
- [x] 重复运行与方差报告：`calibrate --repeats N`。报告均值和范围；退出标准按均值判定，且最差一次不能越过阈值。每个秘密标出猜到场次是否稳定
- [x] 判卷是否靠谱：不另做抽样复核工具。看 `calibrate --out` 里的猜测原文，对照故事真相，由人直接审
- [x] 不把校准结果写入 Langfuse 数据集。每次调用已有追踪；换提示词、换模型时对比 JSON 报告即可
- [跳过] 网文章评 / 本章说导入。不收集章评，也不逐章人审。

说明：漏报的判定是“模拟器在真人猜到的那一场或更早达到 `suspect`”。比真人早很多场才猜到不算漏报，但会在每个秘密的时间差（`offset`）里体现，过早说明模拟器偏敏感。

### 需要人做的

下面两件按指令跳过，不阻塞后续代码，也不要再请人做。

- [跳过] 看 [`stories/REVIEW.md`](../novelforge/eval/calibration/stories/REVIEW.md)。这份对照只作为程序试跑材料。
- [跳过] 没看过结局的人填问卷。不采集真人问卷。

### 程序做的

- [x] 三篇原创短篇（`stories/`）：切场、秘密、探针、`ask_from`。污染检查全部 clean
- [x] 用 `deepseek-v4-pro` 跑完三个画像，对照表在 `stories/REVIEW.md`
- [跳过] 网文章评导入。不收集章评，也不逐章人审。

### 退出标准

- 模拟器信心与真人均值的 Spearman 相关 ≥ 0.6，**且**不低于真人内部一致性上限的 80%（上限本身低于 0.6 时，以 80% 上限为准，并记录原因）
- 漏报率 < 20%（真人在某场猜到的秘密，至少一个画像在同一场或提前一场达到 `suspect`）
- 误报率 < 20%（防止“永远说猜到了”的模拟器通过）
- 跳读一致性有一个记录在案的基线（不设门槛，P3 用作对照）

### 达不到时

1. 调提示词 → 换模型 → 增加画像 → 改为多次采样取众数
2. 仍达不到：G5 / G6 改为**半自动模式**——模拟器预警 + 人审确认。这是正式方案，不是失败；后续阶段的闸门接口需要支持“待人审”状态

---

## P2 最小闭环（短篇）

**目标**：从一段创意端到端生成一部 8–10 场的悬疑短篇。

### 交付

- [x] 架构师：创意 → Canon（真相、秘密、揭示计划）。`roles/architect.py`
- [x] 规划器：Canon → 场景卡。`roles/planner.py`
- [x] **行为指令最简版**：每场 `directives` 只写可见行为。含未揭示秘密原文的指令会被删掉；本场 `must_reveal` 的秘密可以留下，否则揭示场写不出来。完整版见 P4
- [x] 指令泄露检查最简版：读者模拟器只读指令文本，猜到 `suspect` / `certain` 就重写一次，仍泄露则丢掉指令。`roles/directives.py`
- [x] 写手、修订者（整场重写；定点修改见 P4）
- [x] 闸门：
  - G1 字面泄底：精确子串（至少 2 字）+ 汉字二元组近似（至少 8 字、重合 ≥ 0.8）。**bge-m3 仍不接入**，测试保持离线
  - G3 篇幅：汉字数与空格分词取较大值
  - G5 推断式泄底：任一画像的信心高于揭示计划允许的档位
  - G6 揭示越权：计划不允许 `certain` 时出现了 `certain`
  - G7 暗示失效最简版：`hint` 节点上所有画像仍是 `none`
  - G8 张力：画像均值低于目标 0.2 以上
- [x] 单场状态图和全书状态图跑通；`checkpoints.sqlite` 断点续跑；`rollback_scene` 按场景回滚
- [x] CLI：`init` → `plan` → `write` → `manuscript/book.md`
- [x] 对照组：`baseline` 把同一创意一次写成 `manuscript/baseline.md`，不经 Canon 和闸门

### 退出标准

代码路径已通。下面四条都要真人，按指令跳过，不作为继续开发的门槛。

- [跳过] 端到端用真实模型生成一部 8–10 场悬疑短篇并人工验收（命令已支持 `--scenes`，离线测试用 2 场）
- [跳过] 成稿中被真人提前猜中的秘密 ≤ 1 个
- [跳过] 揭示计划中“应开始怀疑”的节点，真人多数达到 `hint` 及以上
- [跳过] 与对照组做真人盲测

---

## P3 节奏控制

**目标**：解决“进展慢”。

### 交付

- [x] 场景卡 `pace` 档位与篇幅预算。`slack/steady/tight/sprint` 各有汉字预算（900/700/480/280）。规划时按张力曲线覆盖 `pace`、`length`、`tension_target`。写手和修订者的系统提示按档位换成不同写法，不是同一句里带一个参数。`sprint` / `tight` 的长段、`slack` 的一整块会被篇幅前的形状检查退回重写
- [x] G9 拖沓：读者标记想跳过的段落占比 ≥ 15% 就拒收，并把下一稿的 `pace` 收紧一档
- [x] G10 空转钩子：`ending_hook` 必须出现在非结局场的正文里，`answers_hook` 必须出现；读者上一场的问题若从正文和“还想知道”里一起消失，也拒收。原因不引用问题原文
- [x] 张力曲线：目标曲线先升、中段喘一口气、结尾再抬高。连续两场低于目标 0.2 时，下一场改成 `sprint` 并抬高目标（强制反转）。连续两场高于目标 0.15 时，下一场改成 `slack` 并降低目标（小回报）

### 退出标准

代码门槛已经接上。和真人对比的三条按指令跳过。

- [x] 跳读率 ≥ 15% 由 G9 拒收。与 P1 真人跳读基线对照已跳过
- [跳过] 实际张力曲线与目标曲线的偏差比 P2 减少一半（没有真人对照样本）
- [跳过] 真人盲测中，“节奏拖沓”和“太快”的反馈都比 P2 少

---

## P4 写作质量

**目标**：伏笔自然、文风稳定、修订成本可控。

### 交付

- [x] 行为指令层完整版：规划器从 Canon 派生“只有表现、没有原因”的指令；因果句被截断，暗示场补一条可见异常。指令泄露检查纳入主闸门（`gates/behavior.py`），原因里不写秘密原文
- [x] 线索账本与强度预算；G5 改为按线索累计计算。`clues is None` 时仍用 P2 的计划上限
- [x] G7 暗示失效完整版：暗示场没人起疑、当场变成 certain、之后掉回 none、强度偏离 light/heavy 预算、暗示场没有公开线索
- [x] POV 状态与 G2 越界检测：写到被挡住的事实，或写进另一个人的内心，都拒收。原因不引用被挡住的原文
- [x] 文风示例、禁用清单、G4 禁用句式。默认禁用清单进 BookState；整句照抄至少 12 字的文风示例也会拒收
- [x] 修订者定点修改：只有文风和 POV 违规时，只改那些段。篇幅、节奏、钩子、泄底仍整场重写

### 退出标准

代码路径已通。下面三条都要真人对照，按指令跳过，不作为继续开发的门槛。

- [跳过] 真人盲测中，“伏笔自然”评分比 P3 高
- [跳过] 一次通过率 ≥ 40%（成本可控）
- [跳过] G4 触发率逐轮下降

---

## P5 长篇化

**目标**：稳定生成 30 章以上的作品。

### 交付

- [x] 长篇记忆：每 3 场压成一条公开章节摘要；已回答的问题从读者的未决列表移到归档，不再进写手视图
- [x] 读者模拟器输入改为“章节摘要 + 最近 3 场全文”。提示词版本 `reader-sim-v2`。签名仍只有正文、画像、探针和客户端
- [x] 成本优化：代码闸门（含因果指令）不过，就不跑读者模拟器。指令泄露检查改走小模型 `gate`
- [跳过] 人审节点：Canon、开篇三章、payoff、退回规划器只写入 `review_marks`，不暂停、不等人
- [x] 日志驱动调优：`gate_stats` 记录每个闸门的检查次数和失败次数。`novelforge gates` 指出失败最多的闸门该改哪条提示词

### 退出标准

代码路径已通。下面两条都要长篇真人对照和重新校准，按指令跳过，不作为继续开发的门槛。

- [跳过] 稳定生成 30 章以上，后半部分的泄底率和张力达成度不比前十章差
- [跳过] 摘要输入的读者模拟器重新通过 P1 的校准标准

---

## 风险与对策

| 风险 | 对策 |
| --- | --- |
| 读者模拟器校准不过 | P1 放在最前，不过不往下做；退路是半自动人审模式 |
| 模拟器“永远说猜到了”导致闸门过严 | P1 退出标准同时卡漏报率和误报率 |
| 闸门过严，越写越保守、越写越含糊 | 张力不达标和泄底一样拒收；G7 双向检查；持续监控一次通过率 |
| 校准集被训练数据污染 | 冷门稿件、改写人名地名、污染检查剔除 |
| 校准文本与生成文本分布不同 | 校准集混入 AI 生成的短篇 |
| 行为指令换说法泄露真相 | 指令先砍掉因果从句，再由读者模拟器检查换说法；仍泄露就丢掉指令。原文子串测试只是必要条件 |
| 成本失控 | 闸门分层先便宜后昂贵；修订限轮数；Langfuse 按场景统计成本 |
| 写手模型文笔不够 | LiteLLM 路由，写手模型可随时替换，用 P2 盲测集对比 |
| 长篇状态膨胀 | 更早的场压成章节摘要，读者只读摘要加最近三场全文；已关闭的问题归档 |

---

## 下一步

1. P5 长篇化的代码已落地。`write` 会把每三场压成摘要，读者模拟器只读摘要加最近三场；代码闸门不过就不跑读者模拟器。`novelforge gates` 看哪个闸门失败最多。
2. 不要请人看 `REVIEW.md`，不要采集真人问卷，不要做盲测，也不要在 Canon、开篇、payoff 或重规划处停下来等人。
3. `docs/PLAN.md` 里的代码项到 P5 为止。没有下一批功能阶段。真人退出标准仍全部跳过。网文章评导入不做。bge-m3 继续不接入。
