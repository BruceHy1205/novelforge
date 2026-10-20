# 读者模拟器校准（P1）

目标：证明读者模拟器判断“读者猜到了没有”和真人一致。不过就不进入 P2。

## 流程

1. **准备故事**：每篇写成一个 YAML（格式见 `example/story.yaml`）。
   - 按场景切分，每行一段（段落编号从 0 开始，问卷和模拟器都用这个编号）。
   - 每个秘密写一条**不含答案**的 `probe_question`、真相 `truth`、可选的 `answer_keywords`。
   - `ask_from`：从哪一场开始问这个问题。问题里提到的人或物在正文出现之前不要问，否则问题本身就泄露了信息（例如人物还没出场就问“他和死者什么关系”）。
   - `revealed_in`：故事明确揭示真相的场景。这一场及之后不计分（大家都知道了，算进去会虚高相关性）。
   - 计分窗口是 `[ask_from, revealed_in)`，模拟器和真人问卷都按这个窗口提问。
   - 公开作品要改写人名地名（`renamed: true`）；混入 1–2 篇 AI 生成的短篇（`ai_generated: true`）。
2. **污染检查**：
   ```bash
   uv run novelforge eval contamination stories/*.yaml --models models.yaml
   ```
   模型不看正文就能答对的秘密会标为 `CONTAMINATED`，这类故事要改写或剔除。
3. **生成问卷**，每位读者一份：
   ```bash
   uv run novelforge eval questionnaire stories/a.yaml --reader r01 --out responses/a/r01.yaml
   ```
   问卷已按 `ask_from` 预填好每场要回答的问题和问题原文。读者读完一场填一场，不能回头改。信心只用四档：`none / hint / suspect / certain`。`correct` 由整理数据的人填，留空则由判卷程序判断。
4. **跑校准**：
   ```bash
   uv run novelforge eval calibrate stories/*.yaml --responses responses/ \
       --models models.yaml --repeats 3 --out reports/run-01.json
   ```
   `--personas` 可换读者画像（默认 `personas.yaml` 里的推理迷、普通读者、没耐心的读者）。
   `--judge keyword` 只用关键词判卷，不调模型；默认用模型判卷。
   `--workers` 控制并发调用数（默认 4）。
   `--repeats` 独立重复次数（正式校准用 3）。报告给出均值和范围。退出标准看均值，并且**最差的一次也不能越过阈值**：例如 Spearman 均值过了、但某一次低于目标，结果仍是 FAIL。每个秘密会标出模拟器猜到的场次是否稳定。
   `--fake` 用假模型离线跑通流程，不产生有意义的数字。

   模型输出有随机性：示例故事上连跑两次，各画像的 Spearman 在 0.63–0.97 之间摆动，“模拟器第几场猜到”也会差一场。`--repeats 1` 只适合看格式。

## 模型

默认用火山引擎 Ark agent plan（`https://ark.cn-beijing.volces.com/api/plan/v3`），key 从环境变量 `ark_plan_api_key` 读取。读者模拟器用 `deepseek-v4-pro`，判卷用 `deepseek-v4.1-flash`。换模型改 `models.yaml` 的 `roles`；示例故事上一次完整校准（3 个画像 × 4 场）约 2 分钟。

## 怎么计分

每个“场景 × 秘密”是一个格子。每位读者（真人或模拟）在每个格子上得到一个**有效信心**：猜对了就是他报的档位；猜对一部分最多算 `hint`；猜错算 `none`。

| 指标 | 定义 | 退出标准 |
| --- | --- | --- |
| Spearman（集成） | 三个画像有效信心的均值 vs 真人均值，跨全部格子 | ≥ 0.6，且 ≥ 真人上限的 80%；上限 < 0.6 时以 80% 上限为准 |
| 真人上限 | 真人随机分两半，两半均值的 Spearman，重采样取平均 | 参照值 |
| 漏报率 | 真人多数在第 N 场达到 `suspect`，而所有画像在第 N 场及之前都没达到 | < 20% |
| 误报率 | 真人多数仍是 `none` 的格子里，任一画像已到 `certain` 的比例 | < 20% |
| 跳读重叠 | 每个画像标记的跳读段落 vs 至少半数真人标记的段落（Jaccard） | 只记录基线 |

误报率是为了防止“永远说猜到了”的模拟器靠漏报率为 0 通过。

## 关于 `example/`

`example/` 里是为演示格式而写的合成故事和合成问卷，**不是真实读者数据**，不能用来判断模拟器好坏。
