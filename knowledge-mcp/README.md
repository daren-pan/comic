# knowledge-mcp

把**仓库文档**（README / NOTES / docs / SQL schema / OpenAPI）和**用户资料**
（Word / Excel / Markdown）建成一个可检索的知识库，通过 **MCP stdio** 交给 Agent 使用。

**只读、只检索**：不调用生成模型，不写数据库，不对外暴露端口。

---

## 与 chat-service 的分工

两个 RAG 共用 embedding 与 Chroma 技术栈，但**索引完全分开**，互不影响：

| | chat-service | knowledge-mcp |
|---|---|---|
| 语料 | FAQ + 漫画作品 | 项目文档 / schema / OpenAPI / 用户资料 |
| 对外 | HTTP `:8001`（api 转发，对外） | MCP stdio（本地 Agent 拉起，不对外） |
| 生成 | 有 `/ask`（调对话模型） | **只检索** |
| 索引目录 | `data/rag_lab` | `data/project_rag` |
| 集合 | `comic_kb_*` | `project_kb_*` / `project_kb_message_*` |

---

## 能力边界

**做：**

- 语义检索 + 关键词（BM25）双路召回，按名次融合；
- 命中后按 `doc_id` 回读**整个小节**（Markdown / SQL），或回读单条 chunk（Word / Excel / 接口）；
- 索引过期检测（改了文档没重建，能查出来）；
- message 表的独立增量索引（走 api 的内部只读接口）。

**不做：**

- **不索引代码**。找函数/符号请用 `ripgrep` / AST，语义检索在这件事上必输；
- 不调生成模型（那是 chat-service 的事）；
- 不对外提供 HTTP 端口，不做鉴权（只给本机 Agent 用）。

---

## 文档地图

| 文档 | 管什么 | 什么时候看 |
|---|---|---|
| **README.md**（本文件） | 是什么、能做什么、去哪看 | 第一次接触 |
| [ARCHITECTURE.md](docs/ARCHITECTURE.md) | 数据流、切分、分词、检索、集合指纹等**设计** | 要改检索/切分/索引时 |
| [OPERATIONS.md](docs/OPERATIONS.md) | **运维手册**：安装、建索引、接 MCP、故障排查 | 日常操作、出问题 |
| [CONFIG.md](docs/CONFIG.md) | **配置参考**：每个环境变量的默认值与影响 | 调参、换模型、换目录 |
| [docs/NOTES.md](docs/NOTES.md) | **踩坑与实测**：只记发生过的问题和实测数据 | 排查怪现象、复盘 |
| [EVAL.md](docs/EVAL.md) | **评估基线**：黄金题集、指标、当前成绩 | 改检索前后对比 |
| [BENCH.md](docs/BENCH.md) | **性能基准**：不同取数方式的延迟与准确率 | 评估"值不值得调 MCP" |

> 约定：**设计写在 ARCHITECTURE，操作写在 OPERATIONS，配置写在 CONFIG，
> 踩坑写在 NOTES**。同一件事只在一个文档里展开，其余位置只放一行指针。

---

## 30 秒上手

```bash
# 1. 装依赖（RAG 依赖复用 chat-service 的 venv，这里只补 MCP SDK）
bash scripts/dev.sh bootstrap knowledge

# 2. 建索引（首次约 40 秒，本地 bge、CPU）
bash scripts/kb.sh index

# 3. 直接问
bash scripts/kb.sh ask "&lt;你的问题&gt;"
```

`scripts/kb.sh` 是统一入口，参数原样转给 CLI（`ask` / `search` / `eval` / `index` /
`read` / `doctor` / `stats`），**不用手工设 `PYTHONPATH`**。完整命令见
[OPERATIONS.md](docs/OPERATIONS.md)。

然后在 MCP 客户端里接上（[OPERATIONS.md](docs/OPERATIONS.md) 有两份配置模板），
就能用 `search_knowledge` / `read_knowledge` 了。

---

## 目录

```
knowledge-mcp/
├── run_mcp.py                  # MCP 启动器：注入 sys.path、临时目录、模型缓存
├── devui.py                    # 调试界面后端（FastAPI，只提供 /api/*）
├── devui-web/                  # 调试界面前端（Vue 3 + Vite）
├── README.md                   # 导读（本文件，留在模块根）
├── docs/                       # 其余职责文档（一份一个职责）
│   ├── ARCHITECTURE.md         # 设计
│   ├── OPERATIONS.md           # 运维手册
│   ├── CONFIG.md               # 配置参考
│   ├── NOTES.md                # 踩坑与实测
│   ├── EVAL.md                 # 评估基线
│   └── BENCH.md                # 性能基准
├── pyproject.toml / requirements.txt
├── src/comic_rag_mcp/
│   ├── config.py               # 路径、阈值、集合指纹
│   ├── chunker.py              # 标题树切分，代码块/表格保护
│   ├── corpus.py               # Markdown / SQL / OpenAPI 加载
│   ├── external.py             # Word / Excel / Markdown 外部文档
│   ├── tokenizer.py            # 分词后端（mixed / jieba / bigram）
│   ├── lexical.py              # BM25 词面索引
│   ├── indexer.py              # Chroma 构建、manifest、过期检测
│   ├── retriever.py            # 双路召回 + RRF 融合 + 回读
│   ├── rerank.py               # 可选重排（CrossEncoderReranker，默认关）
│   ├── message_indexer.py      # message 表 → 独立增量集合
│   ├── message_retriever.py    # message 检索 / 回读 / 统计
│   ├── server.py               # FastMCP 工具定义
│   ├── cli.py                  # doctor / index / search / read / stats / eval
│   └── __main__.py             # stdio 入口
└── tests/                      # 切分 / 语料 / 分词 / 融合 / 索引 / 消息 单测
```
