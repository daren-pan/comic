# knowledge-mcp —— 项目知识库 RAG（MCP）

把仓库里的 **README / NOTES / docs / SQL schema / OpenAPI** 建成一个独立的向量库，
通过 **MCP stdio** 暴露给 Agent 检索。它和 `chat-service` 的客服 RAG 共用 embedding
与 Chroma 技术栈，但**索引完全分开**：

| | chat-service | knowledge-mcp |
|---|---|---|
| 语料 | FAQ + 漫画作品 | 项目文档 / schema / OpenAPI |
| 索引目录 | `crawler-service/data/rag_lab` | `crawler-service/data/project_rag` |
| 集合 | `comic_kb_*` | `project_kb_*` |
| 对外 | HTTP `:8001`（api 转发） | MCP stdio（DSH 直接拉起） |
| 生成 | 有 `/ask`（调对话模型） | **只检索**，不调生成模型 |

## 为什么单独拆

1. **语料形态不同**：客服问答是短文本（FAQ 一节 / 一部作品），项目文档是长文，必须按标题树切；
2. **切分粒度不同**：bge-small-zh 只有 512 token，项目文档不能用客服那套“一节一块”；
3. **生命周期不同**：客服索引随作品库变，项目知识库随文档变，互不影响；
4. **权限不同**：客服对外，项目知识库只给本地 Agent 用。

## 语料范围

**纳入：**

- 根 `README.md`、`AGENTS.md`
- `docs/**/*.md`（`docs/architecture.md` 标 `historical`，默认不检索）
- 各模块 `README.md` / `NOTES.md`
- `crawler-service/src/comic_crawler/sources/*/README.md`
- `comic-core/sql/mysql_schema.sql`：一张表一个 chunk
- `api-service/openapi.json`：一个端点一个 chunk

**排除：**

- `.git/`、`node_modules/`、`.venv/`、`.python/`
- `logs/`、`backup/`、`build/`、`dist/`
- `crawler-service/data/`（图库 / 索引 / 模型缓存）
- `.workbuddy/`、`.agent-shared/`
- 所有 `.env` / 密钥文件
- `sources/guazi/README.md`（只有 fixtures、没有适配器）

## 外部文档（阶段一：Markdown / Word / Excel）

除了仓库自带的工程文档，还能索引**用户自己的资料**（手册、规范、台账）。目录默认
`crawler-service/data/kb_docs/`（运行时数据区，不进 git），也可以用 `COMIC_KB_DOCS_DIR`
指到任意目录（相对路径按仓库根解析，绝对路径直接使用）。

| 格式 | kind | 处理方式 | 回读 |
|---|---|---|---|
| `.md` | `ext_md` | 按标题树切 | `read_mode="lines"`：文件真实存在，能按行号回读整节 |
| `.docx` | `ext_word` | **先转 Markdown**（标题样式 → `#`、表格 → Markdown 表），再按标题树切 | `read_mode="chunk"`：只回命中的那条 |
| `.xlsx` | `ext_excel` | **一行一个 chunk**，表头拼进每一行，空行跳过 | `read_mode="chunk"`：只回命中的那条 |

- 三者进**同一个集合**，`module` 统一为 `external`：`module="external"` 一次拿全部外部资料，
  `kind=ext_excel` 只看某一种格式。
- 放完文件记得重建：`bash scripts/dev.sh knowledge-index`；`knowledge-index --check`
  会把新增/改动的文件列在 `new_files` / `changed_files` 里。
- 阶段一限制：Word / Excel **不做 section 级回读**（原始文件不是纯文本、没有行号），
  只能回命中的那条 chunk；PDF / HTML / PPT 尚未接入。

## 切分规则

**核心约束：`bge-small-zh-v1.5` 的 `max_position_embeddings = 512`。**
中文 1 字约 1 token，所以 1200 字的 chunk 后半段会被 tokenizer **静默截断**。

| 参数 | 值 |
|---|---|
| 目标 chunk | 300–400 个中文字符 |
| 硬上限 | 500 字符 |
| token 硬上限 | 480（留 heading / 特殊 token 余量） |
| 最小 chunk | 120 字符，小于它和相邻小节合并 |
| 长段落重叠 | 50 字符（只在被迫切开一段长文本时） |

具体做法：

1. 按 H1/H2/H3 标题树切；每个 chunk 带 `heading_path`（如 `部署 / 端口与反代`）；
2. 代码块、表格是原子块，不从中间切；
3. 表格超长时按行切，**重复表头**；
4. 单块代码超过 500 字时整块保留（半截代码比长代码更糟），`token_count` 会超 480，
   这是已知例外（本次全库约 800 个 chunk 里 5 个，都是目录树代码块）；
5. child 检索、section 回读：chunk 存 `parent_start` / `parent_end`，
   `read_knowledge` 回读**命中 section 自身**（含其下内容），不再回溯到可能只有
   一句引子的 H2；Markdown/SQL 标记 `read_mode=lines`，OpenAPI 标记 `read_mode=chunk`。

## 分词（词项层）

检索里有两处依赖「把一句话切成词」：**标题/正文加权**（`retriever` 的 boost）和
**BM25 召回**。两处必须用同一个切法，所以统一收在 `tokenizer.py`。

| 后端 | 切法 | 依赖 |
|---|---|---|
| `mixed` | **标识符整体保留 + 部件展开**，中文段交 jieba | `pip install jieba` |
| `jieba` | 词典 + DAG + 最大概率路径 + HMM 未登录词 | `pip install jieba` |
| `bigram` | 英文/数字整词 + 中文两字滑窗 | **零依赖**（只用标准库） |

选择由 `COMIC_KB_TOKENIZER` 控制：

```bash
COMIC_KB_TOKENIZER=auto     # 默认：装了 jieba 就走 mixed，没装退回 bigram
COMIC_KB_TOKENIZER=mixed    # 中英分流：标识符整体 + 部件，中文走 jieba
COMIC_KB_TOKENIZER=jieba    # 纯词典分词（英文标识符会被拆碎）
COMIC_KB_TOKENIZER=bigram   # 零依赖兜底（中文有碎片噪音，英文标识符保整体）
```

**默认是 `mixed`**（`auto` 在有 jieba 时选它）：它是 `jieba` 的超集 —— 中文切法完全一致，
英文/数字标识符额外做到"整体 + 部件"双份。`bigram` 只在没装 jieba 的环境里兜底，
不再作为并列选项。三者的实测对比见 `NOTES.md` §17.6。

`doctor` 会打印**实际生效**的后端，别靠猜。

**用户词典**：`src/comic_rag_mcp/terms.txt`（一行一个词，可带词频/词性，`#` 注释）。
jieba 默认词典不认识「判重 / 图床 / 管理台 / 按需导入」这类项目术语，不配这份词典时
它们会被切碎，**上 jieba 反而比 bigram 更差**。新增模块术语时一并补进来。

> ⚠️ **换分词器 = 换打分刻度**。BM25 的分数是「每个词的稀有度 × 词频 × 长度折扣」求和，
> 分词一变，加数个数、词频口径、文档长度基准、IDF 分布全变。换后端后**必须重标阈值、
> 重跑评估集**（`bash scripts/dev.sh knowledge-eval`，基线见 `EVAL.md`）——
> 和换 embedding 模型是同一类问题。

## 检索：双路 + RRF 融合（阶段二）

`search_knowledge` 默认走**混合检索**：语义向量 + BM25 词面，各出候选后按**名次**融合。

| mode | 行为 | 用途 |
|---|---|---|
| `hybrid`（默认） | 向量 + BM25 → RRF 融合 | 生产 |
| `vector` | 只走语义（等价于旧行为） | 回退 / 对照 |
| `lexical` | 只走 BM25 | 调试「字面到底能捞到什么」 |

- 每条命中的 `sources` 说明它来自哪一路（`vector` / `lexical` / 两者都有）；
  `lexical_score` / `matched_terms` 让你看到**是被哪几个词捞上来的**。
- ⚠️ **`score` 的含义随模式变化**：`vector` 模式是余弦相似度（0~1）；
  `hybrid` 模式是 RRF 分，量级 `1/(60+名次)`（约 0.016）。**不要拿固定阈值卡 `score`**——
  要判断"像不像"请读 `vector_score`。
- `min_score` 阈值**只作用在向量那一路**：融合后分数量级完全不同，拿 0.45 卡会一条不剩。
- 回退开关：`COMIC_KB_HYBRID=0` 时完全回到纯向量（`mode` 默认变 `vector`）。

## 索引

- 目录：`crawler-service/data/project_rag`
- 集合：`project_kb_<embedding + chunker 指纹>`（v2 实测 `project_kb_61e9b771`）
- 必须 cosine：`collection_metadata={"hnsw:space": "cosine"}`
- `manifest.json`：文件 sha1 / 大小 / chunk 数、embedding、切分版本、构建时间、耗时

第一版全量重建；文档量上来后再按 manifest 的 `sha1` 做增量。

检查索引是否过期（不重建，stale 时 exit 1）：

```bash
bash scripts/dev.sh knowledge-index --check
```

## 安装

RAG 依赖与 chat-service 共用同一个 venv，额外只装 MCP SDK：

```bash
bash scripts/dev.sh bootstrap knowledge
```

等价于：

```bash
crawler-service/.venv/Scripts/python.exe -m pip install \
  -r knowledge-mcp/requirements.txt \
  -i https://mirrors.aliyun.com/pypi/simple
```

## 建索引 / 检索

```bash
# 全量重建（首次约 30~40 秒，本地 bge CPU）
bash scripts/dev.sh knowledge-index

# 或直接跑 CLI
PYTHONPATH="knowledge-mcp/src;chat-service/src;comic-core/src" \
  crawler-service/.venv/Scripts/python.exe -m comic_rag_mcp.cli doctor

PYTHONPATH="knowledge-mcp/src;chat-service/src;comic-core/src" \
  crawler-service/.venv/Scripts/python.exe -m comic_rag_mcp.cli search "JWT 角色三档"

PYTHONPATH="knowledge-mcp/src;chat-service/src;comic-core/src" \
  crawler-service/.venv/Scripts/python.exe -m comic_rag_mcp.cli read "<doc_id>"

PYTHONPATH="knowledge-mcp/src;chat-service/src;comic-core/src" \
  crawler-service/.venv/Scripts/python.exe -m comic_rag_mcp.cli stats
```

`knowledge-index` 会自动设置 DSH 需要的 `TMP/TEMP/TMPDIR`、`FASTEMBED_CACHE_PATH`、
`COMIC_RAG_INDEX_DIR`；普通终端不用手工 export。

## MCP 配置

### DSH

`~/.dsh/profiles/desktop/cordis.patch.yml` 已加：

```yaml
- insert:
    - id: mcp-comic-knowledge
      name: '@deepseek-ai/dsh-mcp-client'
      config:
        serverName: comic-knowledge
        transport: stdio
        command: D:/software/RuoYi/comic/crawler-service/.venv/Scripts/python.exe
        args:
          - D:/software/RuoYi/comic/knowledge-mcp/run_mcp.py
        failOnStartupError: true
```

`run_mcp.py` 负责把 `knowledge-mcp/src`、`chat-service/src`、`comic-core/src` 放进
`sys.path`，并设置项目内临时目录 / 模型缓存 —— 这样 MCP 客户端不需要支持 `env` 字段。
改完 profile 后重启 DSH（或在连接器管理页重新 Trust）。

### 通用 MCP 客户端

模板见 [`.agent-shared/mcp/knowledge.json`](../.agent-shared/mcp/knowledge.json)：

```json
{
  "mcpServers": {
    "comic-knowledge": {
      "type": "stdio",
      "command": "<PROJECT_PYTHON>",
      "args": ["<REPO_ROOT>/knowledge-mcp/run_mcp.py"]
    }
  }
}
```

## MCP 工具

| 工具 | 作用 | 关键参数 |
|---|---|---|
| `search_knowledge` | 文档语义检索，返回精简命中 | `query`、`top_k`、`kind`、`module`、`include_historical` |
| `read_knowledge` | 按 `doc_id` 回读文档命中 section 全文 | `doc_id` |
| `knowledge_stats` | 文档索引摘要 + stale 状态 | `detail`（默认 false） |
| `search_messages` | **message 表**语义检索 | `query`、`top_k`、`level`、`kind` |
| `read_message` | 按 `doc_id` 回读一条消息 | `doc_id`（`message:<id>`） |
| `message_stats` | message 索引状态 | 无 |

`search_knowledge` 返回示例：

```json
{
  "query": "<用户问题>",
  "hits": [
    {
      "doc_id": "<path>#<heading>-<hash>-0",
      "title": "<文档标题>",
      "path": "<path>",
      "heading": "<小节标题>",
      "heading_path": "<文档 / 小节>",
      "kind": "module_readme",
      "module": "<module>",
      "status": "current",
      "score": 0.0,
      "vector_score": 0.0,
      "heading_boost": 0.0,
      "module_boost": 0.0,
      "body_boost": 0.0,
      "snippet": "<300 字以内摘要>",
      "start_line": 0,
      "parent_start": 0,
      "parent_end": 0
    }
  ],
  "count": 1,
  "backend": "local",
  "elapsed_ms": 0
}
```

`read_knowledge` 返回 `content`（命中 section 的 Markdown/SQL 原文）与
`start_line/end_line`；OpenAPI 端点没有稳定行号，返回完整 endpoint chunk
（`read_mode=chunk`）。

### 过滤值

- `kind`：`root_doc` / `module_readme` / `module_notes` / `design_doc` /
  `deploy_doc` / `source_readme` / `schema` / `api`
- `module`：`project` / `core` / `crawler` / `api` / `scheduler` / `chat` /
  `web` / `front` / `deploy` / `docs` / `scripts` / `tools` / `knowledge`

## message 数据源（内部接口）

`message` 表**不直接连库**，而是由 api 的只读接口暴露：

```text
GET /api/internal/knowledge/messages?cursor=0&limit=200
X-Service-Token: <HMAC>
```

接口按 `id` 升序返回全量 message 行（不做账号过滤）；message 表是追加式，
没有 `updated_at`，所以增量游标就是 `id > last_id`。

本地开发用默认 `COMIC_JWT_SECRET`（`comic-demo-secret-change-me`）；生产必须
api 和 indexer **显式设置同一个强随机值**，否则默认密钥是公开的。

建索引：

```bash
# 首次 / 清理 purge 留下的旧向量
bash scripts/dev.sh message-index --full

# 增量（默认）：从 manifest.last_id 继续
bash scripts/dev.sh message-index

# 只看状态
bash scripts/dev.sh message-index --stats
```

产物：

- 集合：`project_kb_message_f0493561`（当前 12 条消息）
- manifest：`crawler-service/data/project_rag/message_manifest.json`
- 与文档索引 `project_kb_61e9b771` **分开**，互不影响。

MCP 工具：

```json
{"query": "定时任务执行完成", "top_k": 3, "level": "info"}
```

`search_messages` 返回 `doc_id=message:<id>`、`title`、`kind`、`level`、`source`、
`task_id`、`created_at`、`score`、`snippet`；`read_message` 返回完整文本。

边界：

- indexer 只 **GET** 内部接口，不修改/删除 MySQL；
- `--full` 只删本地 Chroma 集合，不动 message 表；
- 消息正文可能包含定向/管理员通知，目前全部进本地索引；`toUserId` 只作为
  `targeted` 元数据（0/1），不写入正文；
- **定时还没接**，目前手动跑 `message-index`；后续再接 Task Scheduler / 独立进程。

## 当前实测

2026-11-03 v2 建库：

- **38 个文件 / 约 800 个 chunk / 800+ 个向量**（最新值以 `knowledge_stats` 为准）
- 类型分布（约）：`module_notes` 270、`module_readme` 175、`deploy_doc` 88、
  `design_doc` 75、`source_readme` 68、`api` 63、`root_doc` 46、`schema` 26
- `historical` 27 个（`docs/architecture.md`）
- 全量构建 **约 30–50 秒**（本地 bge 冷启动；模型热后约 32 秒）
- 超过 480 token 的 chunk 5 个，均为目录树代码块（有意保留）
- 20 条黄金问题 **Recall@5 = 20/20（100%）**；但 top-1 仍有 2 条不是最理想，
  详见 [EVAL.md](EVAL.md)
- 公平延迟/准确率基准见 [BENCH.md](BENCH.md)：`file_agent` vs `mcp_single` vs `mcp_agent`
- `knowledge_stats` 返回摘要与 `stale`；需要完整 manifest 时传 `detail=true`

## 已知限制

- **只索引文档，不索引代码**。找函数/符号请用 `ripgrep` / AST 符号索引，不要指望向量；
- `docs/architecture.md` 是 v1 设计稿，默认过滤；`tools/README.md` 仍有 0001~0009 的旧说法，
  属于文档本身待修，不是索引问题；
- 代码块超 500 字时整块保留，可能被 bge 截断；
- 第一版全量重建，没有增量；文档改动后重跑 `knowledge-index`，
  或先用 `knowledge-index --check` 看是否过期；
- `read_knowledge` 最多返回 6000 字符，超长会截断并标记 `truncated`；
- 索引缺失/为空 / 版本不匹配时，`search`/`read` 会抛 `ToolError`，
  MCP 客户端看到 `isError=true`，不再返回空 hits 假装“没有资料”。

## 目录

```
knowledge-mcp/
├── pyproject.toml / requirements.txt
├── run_mcp.py                # MCP 启动器（设 sys.path / temp / cache）
├── README.md / NOTES.md
├── src/comic_rag_mcp/
│   ├── config.py             # 路径 / 阈值 / 集合指纹
│   ├── chunker.py            # 标题树切分 + 代码块/表格保护
│   ├── corpus.py             # Markdown / SQL / OpenAPI 加载
│   ├── indexer.py            # 文档 Chroma 全量构建 + manifest
│   ├── retriever.py          # 文档检索 + 标题加权 + 回读
│   ├── message_indexer.py    # message 内部接口 → 独立增量集合
│   ├── message_retriever.py  # message 检索 / 回读 / stats
│   ├── server.py             # FastMCP 工具
│   ├── cli.py                # doctor / index / search / read / stats
│   └── __main__.py           # stdio 入口
└── tests/                    # 切分器 / 语料 / stale / message 单测
```
