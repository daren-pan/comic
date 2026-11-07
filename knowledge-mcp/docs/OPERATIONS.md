# 运维手册

> 这份文档只讲**怎么操作、怎么排查**。设计取舍看 [ARCHITECTURE.md](ARCHITECTURE.md)，
> 参数含义看 [CONFIG.md](CONFIG.md)。

## 速查

| 我要做什么 | 命令 |
|---|---|
| 装/补依赖 | `bash scripts/dev.sh bootstrap knowledge` |
| 全量重建文档索引 | `bash scripts/dev.sh knowledge-index` |
| 只检查索引是否过期 | `bash scripts/dev.sh knowledge-index --check` |
| 看配置与索引状态 | `bash scripts/dev.sh knowledge-index --check` 或 CLI `doctor` / `stats` |
| 试检索（不调模型） | CLI `search "<问题>"` |
| 看命中全文 | CLI `read "<doc_id>"` |
| 跑评估集 | `bash scripts/dev.sh knowledge-eval` |
| 重建 message 索引 | `bash scripts/dev.sh message-index`（`--full` 全量 / `--stats` 只看状态） |

## 前置条件

- Python 环境：项目内 `crawler-service/.venv`（RAG 依赖与 chat-service 共用）；
- 本地模型缓存：`crawler-service/data/fastembed_cache`（首次建索引会自动下载约 90MB）；
- 不需要 MySQL（文档索引不连库；message 索引走 api 的 HTTP 接口）。

## 一、安装依赖

```bash
bash scripts/dev.sh bootstrap knowledge
```

等价于手动执行：

```bash
crawler-service/.venv/Scripts/python.exe -m pip install \
  -r knowledge-mcp/requirements.txt \
  -i https://mirrors.aliyun.com/pypi/simple
```

> RAG 主依赖（langchain / chromadb / fastembed / jieba）由 chat-service 那份装进同一个 venv，
> `knowledge-mcp/requirements.txt` 只补 MCP SDK 与文档解析库。

## 二、建索引

### 全量重建（唯一支持的建法）

```bash
bash scripts/dev.sh knowledge-index
```

- 首次约 30~50 秒（本地 bge、CPU；模型热后约 30 秒）；
- 会先删集合再重建 —— **不是增量**。文档量到万级再考虑增量；
- 自动设置 `TMP/TEMP/TMPDIR`、`FASTEMBED_CACHE_PATH`、`COMIC_RAG_INDEX_DIR`，
  普通终端不需要手工 export。

### 检查是否过期（不重建）

```bash
bash scripts/dev.sh knowledge-index --check
```

输出 `changed / new / missing` 三类文件；过期时退出码为 1，可直接接进 CI 或 pre-commit。

### 加了外部文档（Word / Excel / Markdown）

1. 把文件放进 `crawler-service/data/kb_docs/`（或用 `COMIC_KB_DOCS_DIR` 指到别处）；
2. 跑一次 `bash scripts/dev.sh knowledge-index`；
3. 用 `kind=ext_word` / `ext_excel` / `ext_md` 或 `module=external` 过滤验证。

### message 索引

```bash
bash scripts/dev.sh message-index --full    # 首次 / 清理 purge 残留
bash scripts/dev.sh message-index           # 增量（从 last_id 继续）
bash scripts/dev.sh message-index --stats   # 只看状态
```

需要 api 在跑（它提供内部只读接口）。**定时刷新还没接**，目前手动跑。

## 三、接入 MCP

启动器是 `knowledge-mcp/run_mcp.py`：它负责把三个 `src` 目录塞进 `sys.path`，
并设置项目内的临时目录与模型缓存 —— **所以 MCP 客户端不需要支持 `env` 字段**。

### DSH（cordis profile）

```yaml
- insert:
    - id: mcp-comic-knowledge
      name: '@deepseek-ai/dsh-mcp-client'
      config:
        serverName: comic-knowledge
        transport: stdio
        command: <VENV_PYTHON>
        args:
          - <REPO_ROOT>/knowledge-mcp/run_mcp.py
        failOnStartupError: true
```

改完 profile 需要重启 DSH（或在连接器管理页重新 Trust），工具才会回到索引。

### 通用 MCP 客户端

模板见 [`../../.agent-shared/mcp/knowledge.json`](../../.agent-shared/mcp/knowledge.json)：

```json
{
  "mcpServers": {
    "comic-knowledge": {
      "type": "stdio",
      "command": "<VENV_PYTHON>",
      "args": ["<REPO_ROOT>/knowledge-mcp/run_mcp.py"]
    }
  }
}
```

### 工具一览

| 工具 | 作用 | 关键参数 |
|---|---|---|
| `search_knowledge` | 文档检索，返回精简命中 | `query`、`top_k`、`kind`、`module`、`include_historical`、`mode` |
| `read_knowledge` | 按 `doc_id` 回读小节全文 | `doc_id` |
| `knowledge_stats` | 索引摘要 + 过期状态 | `detail`（默认 false） |
| `search_messages` | message 表检索 | `query`、`top_k`、`level`、`kind` |
| `read_message` | 回读一条消息 | `doc_id`（`message:<id>`） |
| `message_stats` | message 索引状态 | 无 |

## 四、日常检查清单

每周或改动文档后，按顺序过一遍：

```bash
bash scripts/dev.sh knowledge-index --check     # 1. 索引是否过期
crawler-service/.venv/Scripts/python.exe -m comic_rag_mcp.cli doctor   # 2. 生效的后端与条数
```

`doctor` 要确认三件事：

1. **embedding 后端**是否符合预期（`local` = 本地 bge，`openai` = 云端）；
2. **分词后端**（`mixed` / `jieba` / `bigram`）—— 与预期不符会导致结果"莫名变了"；
3. **已建索引条数**与「语料 chunk 数」是否一致 —— 不一致就是过期。

> ⚠️ 做任何检索效果对比之前，先看这里的两个数字。**曾经在过期索引上跑完一整轮 A/B，
> 结论全是错的。**

## 五、故障排查

| 现象 | 最可能的原因 | 处置 |
|---|---|---|
| `search` 返回空、或 `ToolError` | 索引没建 / 集合为空 / 版本不匹配 | 跑 `knowledge-index`；再 `stats` 看 `stale` |
| `code: 14 unable to open database file`<br>或 `WinError 5 拒绝访问` | 系统临时目录不可写（受限会话） | 用 `dev.sh` 或 `run_mcp.py` 启动（已自动改 TMP）；手跑 CLI 时自己 export |
| 首次建索引卡住 / 报模型下载失败 | 直连 HuggingFace 不通 | 设 `HF_ENDPOINT=https://hf-mirror.com` |
| 检索结果全是无关文档 | ① 索引过期<br>② 分词后端不是预期<br>③ 向量后端是 `hash` 占位 | 依次查 `doctor` 三项 |
| 答案里出现"不存在的功能" | 语料里没有，但检索给了低分噪音 | 看 `min_score`；看命中的 `sources` 与 `matched_terms` |
| 两个语义相近的文档总抢第一 | RRF 平局，靠 doc_id 排序 | 用 `mode=vector` 对照；根本上需要二次重排（尚未实现） |
| MCP 工具在客户端里不出现 | profile 未重载 / 未 Trust / 路径写错 | 重启 DSH 或重新 Trust；核对 `run_mcp.py` 绝对路径 |
| 改了文档但检索没变化 | 没重建索引；或改了 `page_content` 拼法但没升 `CHUNKER_VERSION` | 重建；必要时升版本号 |
| Word / Excel 命中后内容不全 | 二进制源没有行号，只能回单条 chunk | 属于已知限制，看原文件 |

### 判断"问题出在检索还是生成"

本模块**只做检索**，所以：

| 现象 | 问题在哪 | 换生成模型有用吗 |
|---|---|---|
| `search` 命中的不是该命中的 | 切分 / 分词 / 阈值 / 加权 | ❌ 完全没用 |
| `search` 命中对了，答案仍不对 | 在调用方（chat-service 的 prompt 或模型） | ✅ 可能有用 |

**调试永远先用 `search`，不要一上来就换模型。**

## 六、换模型 / 换分词的正确顺序

1. 改环境变量（见 [CONFIG.md](CONFIG.md)）；
2. **重跑评估集**，记录基线（`EVAL.md`）；
3. 若换的是 embedding 模型 → 必须重建索引（集合名会自动变，旧集合保留）；
4. 若换的是分词器 → **不需要**重建向量索引（BM25 是内存索引，重启即按新分词重建），
   但必须重标阈值与加权，因为打分刻度变了；
5. 把"旧 vs 新"的对比写进 [NOTES.md](NOTES.md)，别只写"改了"。

## 七、维护约定

- **改了被索引的文档**（README / NOTES / docs / schema / OpenAPI）→ 跑一次 `knowledge-index`；
- **新增模块术语**（如"判重""图床"这类词典不认识的词）→ 补 `src/comic_rag_mcp/terms.txt`；
- **改了切分规则或 `page_content` 拼法** → `CHUNKER_VERSION` 加一（否则旧向量会继续被复用，
  且不报错）；
- **不要往 README 里写会与真实问题重合的示例问句** —— 自文档会被索引，示例会污染检索
  （已有前车之鉴，见 [NOTES.md](NOTES.md)）。
