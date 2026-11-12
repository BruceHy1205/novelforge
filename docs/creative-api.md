# 创意入库 API

外部创意系统把已经写好的故事简报交给 NovelForge。NovelForge 只做校验、落盘、入队，然后走现有的 `plan` / `write` / 闸门。调用方已经给了 Canon 或大纲时，工厂不会再让架构师或规划器另写一版，也不会删掉 `projects/<slug>/`。

控制台原来的一行一批（`/api/topics`、`/api/books`）不变。这条面只在 `/api/v1/creative/`。

鉴权与控制台相同：本机信任，没有单独的 token。交互式结构在服务起来后的 [`/docs`](http://127.0.0.1:8765/docs)（请求体就是仓库里的 `Canon`、`SceneCard`、`ModelRouting`）。下面是可以直接调用的例子。默认地址 `http://127.0.0.1:8765`。工厂默认暂停，入队之后要 `POST /api/control/start` 才会开跑；演练不调模型时先 `PUT /api/settings` `{"dry_run": true}`。

## 三种模式

| 模式 | 什么时候 | 工厂做什么 |
| --- | --- | --- |
| `plan_from_idea` | 只给了 `idea` / `core` | 现有路径：架构师 → 规划器 → 写 |
| `keep_canon` | 给了完整 `canon` | 写入 `canon.yaml`，跳过架构师（`skip_architect`），再规划、再写 |
| `keep_outline` | 给了 `canon` 和 `cards` | 两个都落盘，跳过架构师和规划器（`skip_planner`），直接写和闸门 |

`keep_outline` 同时置上 `keep_canon`。`idea.txt` 用请求里的 `idea`（可加 `core`）；没有 idea 时从 Canon 的标题、前提和 `story` 公开字段拼一句，好让旧管线还有可读的创意字符串。已经落盘的 Canon / 场景卡仍是源。

`POST /books` 可以一次带上 canon、cards、models、run。也可以先建书，再用 PUT 补。

密钥只走环境变量名 `provider.api_key_env`（例如 `ark_plan_api_key`）。请求里出现 `api_key`，或 `api_key_env` 不是合法的变量名，都会被拒绝，不会写进 `models.yaml`。

## 创建

只给创意。书先记在库里，`enqueued` 为 false，工厂不会动它，直到 `/run`。

```bash
curl -s -X POST http://127.0.0.1:8765/api/v1/creative/books \
  -H 'content-type: application/json' \
  -d '{
    "external_id": "desk-1042",
    "genre": "mystery",
    "idea": "渡口封了，账房连夜离开",
    "chapters": 8
  }'
```

带 Canon（`keep_canon`）和模型路由，并直接进入大纲队列：

```bash
curl -s -X POST http://127.0.0.1:8765/api/v1/creative/books \
  -H 'content-type: application/json' \
  -d '{
    "external_id": "desk-1042",
    "genre": "mystery",
    "canon": {
      "title": "渡口夜话",
      "premise": "账房连夜离开",
      "story": {
        "hook": "渡口封了",
        "protagonist_id": "c1",
        "characters": [
          {"id": "c1", "name": "林舟", "role": "protagonist"},
          {"id": "c2", "name": "周先生", "role": "suspect"}
        ]
      },
      "secrets": [
        {
          "id": "S-1",
          "title": "账房",
          "text": "周先生带走了渡口的账",
          "probe_question": "谁最可疑？"
        }
      ]
    },
    "models": {
      "provider": {"api_key_env": "ark_plan_api_key"},
      "roles": {"writer": "deepseek-v4.1-flash"}
    },
    "run": {"stage": "outline", "keep_canon": true}
  }'
```

同一个 `external_id` 再 POST 一次不会建第二本书（第一次 201，之后 200），响应里的 `id` 相同。后一次如果带了 canon、cards、models 或 run，会补到这本书上。

## 补 Canon、大纲、模型

```bash
curl -s -X PUT http://127.0.0.1:8765/api/v1/creative/books/1/canon \
  -H 'content-type: application/json' \
  -d @canon.json

curl -s -X PUT http://127.0.0.1:8765/api/v1/creative/books/1/outline \
  -H 'content-type: application/json' \
  -d '{
    "cards": [
      {"scene_id": "sc-01", "title": "封渡", "setting": "江边渡口"},
      {"scene_id": "sc-02", "title": "夜账", "setting": "账房"}
    ]
  }'

curl -s -X PUT http://127.0.0.1:8765/api/v1/creative/books/1/models \
  -H 'content-type: application/json' \
  -d '{"provider": {"api_key_env": "ark_plan_api_key"}}'
```

`scene_id` 用 `sc-01` 这种编号。悬疑 Canon 要有 hook、主角、嫌疑人，以及至少一个秘密；爽文改为反派，秘密可以没有。缺了会 400，不会交给模型去补。

## 入队

`stage`：`outline` → `queued`，`trial` → `trial_queued`，`full` → `full_queued`。后面仍是原来的阶段：审核（开着的话）、试读、全书、`done`，失败进 `failed`，毙掉进 `trashed`。

`trial_chapters` 只作用于这本书的试读长度。`stop_at` 是最多写到第几章（试读和全书都不会超过它）。`keep_cards` 与 `keep_outline` 相同。这两个开头标志只会打开，不会把已经注入的书改回“推倒重来”。

```bash
curl -s -X POST http://127.0.0.1:8765/api/v1/creative/books/1/run \
  -H 'content-type: application/json' \
  -d '{
    "stage": "trial",
    "keep_outline": true,
    "keep_cards": true,
    "trial_chapters": 3,
    "stop_at": 3
  }'
```

没有场景卡就进试读或全书，会 400。题材一行一批的书不带这些标志，大纲步骤仍会删掉项目目录再按 idea 重做。创意入库的书带了 `keep_canon` 或 `keep_outline` 时，这一步留下 `canon.yaml`、`scenes/sc-*.yaml`，以及调用方额外放进目录里的文件。`models.yaml` 即使走“从 idea 重做大纲”，也会先抄出来再写回。

## 查询

`GET /api/v1/creative/books/{id}` 的形状与 `GET /api/books/{id}` 相同（书的行、canon、cards、已锁章节、events），并多了 `skip_architect`、`skip_planner`、`busy` 和 `artifacts`（canon、场景卡、正文、models、idea 在工厂目录下的相对路径）。

```bash
curl -s http://127.0.0.1:8765/api/v1/creative/books/1
```
