# chat-service —— RAG 客服服务（独立进程）

给漫画站提供「问一句、答一句」的客服能力。**单独一个容器**，不在 api 进程里。

## 为什么单独拆出来

| 理由 | 具体 |
|---|---|
| 镜像体积 | langchain / chromadb / fastembed 会拉进 **80+ 个传递依赖**，塞进 api 镜像涨 400MB 以上 |
| 内存 | bge 向量模型常驻 **300~500MB**，和主站抢内存；被 OOM 杀掉时**整个网站不可用** |
| 故障隔离 | 这套依赖出问题时只影响客服，浏览/收藏/评论照常 |
| 符合项目已有约定 | `comic-scheduler` 就是同样的思路（独立进程、独立容器） |

## 架构位置

```
浏览器 ──→ comic-api ──(内网 HTTP)──→ comic-chat
            鉴权 / 限流               纯 RAG，不认用户
            （/api/chat/*）           （/ask、/lab/*）
```

**鉴权为什么在 api 而不在这**：`core/security.py` 是 api-service 的模块，搬不过来；而且本服务
不该知道「谁在问」。分工是：**api 认人，chat 认问题**。

**为什么不映射宿主端口**：本服务没有任何鉴权。映射到宿主 = 公网任何人可无限调模型、烧光额度，
而且不知道是谁。只有同一 `backend` 网络的容器能访问 `http://comic-chat:8001`。

## 目录

```
chat-service/
├── pyproject.toml            打包描述（含 package-data：knowledge/faq.md 必须进 wheel）
├── requirements.txt          本地开发用（与 pyproject 的 dependencies 同步）
├── README.md · NOTES.md      本文件 / 踩坑记录
└── src/comic_chat/
    ├── __init__.py           包说明（为什么拆、进程边界）
    ├── __main__.py           `python -m comic_chat` 启动 uvicorn
    ├── app.py                FastAPI：/health、/ask、/lab/*
    ├── schemas.py            请求体（只声明形状）
    ├── cli.py                命令行：doctor / index / search / ask
    └── rag/                  RAG 内核（七步链路，见其 README）
        ├── settings.py · embeddings.py · documents.py
        ├── structured.py     结构化召回（双路召回的第二路）
        ├── index.py · chain.py
        └── knowledge/faq.md  知识源（改完要重建索引）
```

> **改检索逻辑前先读 `rag/README.md` 的「检索设计」一节** —— 那里记了双路召回、
> 文档分离的完整依据，以及 7 个被实测否掉的方案（避免重复试错）。实测数据在 `rag/NOTES.md`。

## 怎么跑

**本地（两个进程都要起）**

```bash
bash scripts/dev.sh up chat     # :8001
bash scripts/dev.sh up api      # :8000（转发到 8001）
```

命令行（不用起服务）：

```bash
cd chat-service
PYTHONPATH="src;../comic-core/src" ../crawler-service/.venv/Scripts/python.exe -m comic_chat.cli doctor
```

**容器**

```bash
bash deploy/up.sh                        # 会一并起 comic-chat
docker compose -f deploy/docker-compose.yml up -d comic-chat   # 只起它
docker compose exec comic-chat python -m comic_chat.cli search "图裂了"
```

首次启动若索引为空会自动建一次（`app.py` 的 `_ensure_index`），约 2 秒。

## 配置

| 变量 | 默认 | 说明 |
|---|---|---|
| `COMIC_LLM_API_KEY` | 空 | 对话模型 key。**不配也能起**，只是问答 503，检索/建索引不受影响 |
| `COMIC_LLM_BASE_URL` | OpenCode Go 网关 | 末尾**不要**带 `/chat/completions` |
| `COMIC_LLM_MODEL` | `deepseek-v4.1-flash` | 旧名 `deepseek-chat` 已退役 |
| `COMIC_CHAT_INDEX_DIR` | `DATA_ROOT/rag_lab` | **容器里必须设成 `/data/rag_lab`**，否则索引写到不可写位置 |
| `COMIC_CHAT_PORT` | `8001` | |
| `COMIC_CHAT_HOST` | `0.0.0.0` | 容器内必须 0.0.0.0；本地可设 127.0.0.1 |
| `HF_ENDPOINT` | — | 国内下载本地模型必须走镜像，否则报 `Could not load model` |

本地填 key 用 `rag/.env`（从 `rag/.env.example` 复制，已被 gitignore）。容器里用 `deploy/.env`。

## 接口

| 端点 | 谁调 | 说明 |
|---|---|---|
| `GET /health` | api / 健康检查 | 后端类型、集合名、向量条数、索引目录 |
| `POST /ask` | api 转发 | `{question, history?}` → `{answer, hits, rewritten, model, elapsedMs}`。**查不到资料且有上文时才改写**，见下方「多轮」 |
| `POST /lab/index` | api 转发（管理员） | 重建索引 |
| `POST /lab/search` | api 转发（管理员） | 只检索，带分数 |
| `POST /lab/ask` | api 转发（管理员） | 完整问答，带 `context` 调试信息 |
| `GET /lab/status` | api 转发（管理员） | 配置自检 |

**这些接口本身不做鉴权**，全部由 api 的 `/api/chat/*` 把门。

## 多轮对话

`history` 由前端带上来（**后端不存会话**，最多 12 条 / 6 轮，两端都会卡）。

关键设计：**改写只在「检索查不到」时触发**，不是每次都改写。

```
① 用原问题检索
     ├─ 命中  → 直接生成                    （1 次模型调用）
     └─ 0 条 + 有上文 → 改写 → 重查 → 生成   （2 次模型调用）
```

不用「像不像追问」来判断，因为实测发现**句式跟能不能检索到无关**：
「我们之前讨论过的那个会员要多少钱」照样 0 命中，而「刚才说的那个收藏怎么取消」能命中。
详见 `src/comic_chat/rag/NOTES.md` 的「多轮对话」一节。

改写结果会通过 `rewritten` 字段回传，前端显示成「理解为：xxx」—— 这是排查多轮有没有生效的唯一线索。

## 依赖方向

```
chat-service → comic-core        （模型 / 路径 / 存储）
chat-service ✗→ api-service      （不依赖，也引用不了它的 core/）
chat-service ✗→ comic-crawler    （不需要 cron / 适配器 / 穿透取图）
```

数据库连接直接建 `MySQLStorage()`，参数走 `COMIC_MYSQL_*` 环境变量 —— 和 api 用的是同一套
环境变量，所以「独立连接」和「同进程连接」在语义上完全等价。
