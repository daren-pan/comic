# knowledge-mcp · 踩坑与实测

> 本文件只记**踩坑 / 实测 / 复盘**；框架与用法见 `README.md`。

## 1. bge-small-zh 只有 512 token，1200 字的 chunk 会被静默截断

`bge-small-zh-v1.5` 的 `config.json` 里 `max_position_embeddings = 512`，
`tokenizer_config.json` 的 `model_max_length` 也是 512。中文 1 字约 1 token，
所以 1200 字的中文 chunk **后半段直接丢**，而且不报错 —— 表现为“明明写在文档里，
检索就是找不到”。

**做法**：目标 300–400 字、硬上限 500 字、token 复核 480；`chunker.py` 用本地
`tokenizer.json` 计数，找不到 tokenizer 时回退字符数（偏保守）。

本次约 800 个 chunk 中 5 个超过 480 token（最大 1042），全部是目录树代码块 ——
代码块不从中间切，接受这个例外。

## 2. `TMP` / `TEMP` / `TMPDIR` 必须三个都改

Windows 上 Chroma 的 Rust SQLite / fastembed 直接读系统临时目录。只改 `TMP`、
不改 `TEMP`，它们仍可能落到 DSH 工作区外不可写的 `AppData\Local\Temp\dsh-*`，
报 `code: 14 unable to open database file` / `WinError 5`。

`run_mcp.py` 和 `dev.sh knowledge-index` 都是**三个一起覆盖**，不是 `setdefault`。
`comic_chat.runtime_env.prepare()` 还会在检测到不可写时兜底到 `DATA_ROOT/tmp`。

## 3. 集合名必须带 embedding + 切分指纹

Chroma 的 `collection_metadata={"hnsw:space": "cosine"}` **只在集合首次创建时生效**；
集合已存在时再传会被静默忽略。所以：

- 集合名 = `project_kb_<backend:model:dim:chunkN 的短哈希>`；
- 换模型 / 改切分规则 → 自动落到新集合，旧索引保留；
- 重建时先 `delete_collection()` 再重开，避免旧集合的 L2 度量继续生效。

## 4. `read_knowledge` 不要走 `get_store()`

`get_store()` 会构造 `get_embeddings()`，本地后端会加载 bge ONNX（约 1 秒）。
回读只需要 Chroma 的 `get()`，不需要 embedding；所以 `retriever.read()` 直接用
`chromadb.PersistentClient(...).get_collection(...)`，避免每次 `read` 白加载模型。

## 5. 标题加权不能带 title / path

第一版加权把 `title`、`path` 也算进去，结果同一篇文档的所有 chunk 都因为文档标题
命中而一起涨分。例如问 “scheduler 为什么独立进程”，`comic-scheduler/README.md`
的每个小节都带 “comic-scheduler … 独立进程”，加权完全失去区分度。

**改为只用 section `heading` 做加权**（最多 +0.12），向量分仍是主体。
查询 “scheduler 为什么独立进程” 后，正确小节从第 2 升到第 1。

## 6. 同一个 H2/H3 切出的多个 child 要去重

一个长小节会切成多个 child，检索时可能同时命中 2~3 个同 heading 的 chunk。
`read_knowledge` 反正会回读整个父小节，所以 `search` 按
`(path, heading_path)` 去重，只保留分数最高的 child —— 否则 top_k 被同一节占满。

## 7. 历史稿 / 过期文档

- `docs/architecture.md`：文件头明确写“v1 设计稿、不是现状”，标 `status=historical`，
  默认检索过滤；否则“项目有没有 Redis”会答出未落地方案。
- `tools/README.md`：仍写迁移 `0001~0009`，实际已到 `0010`。这是文档本身待修，
  索引层无法自动判断；评测时如果命中，先修文档。
- `sources/guazi/README.md`：只有 fixtures、没有适配器，直接排除。

## 8. 72KB 的 `comic-front/NOTES.md`

它一个文件切出 125 个 chunk（全库最多），内容有用但噪声也大。
第一版不特殊处理；如果评测发现它经常挤掉更相关的 README，可以：

- 给 `kind=module_notes` 降权；
- 或把 front 的 NOTES 按主题拆成多个文件。

## 9. SQL / OpenAPI 的切法

- SQL：按 `CREATE TABLE` 块解析，一张表一个 chunk；`VARCHAR(255)` / `DECIMAL(10,2)`
  里的括号不能当块结束，`corpus._find_matching_paren` 做了深度扫描。
- OpenAPI：`paths` 50 个、无 tags，按 method + path 一个 endpoint 一个 chunk，共 63 个；
  端点没有稳定行号，`read_mode=chunk`，`read` 返回完整 endpoint 文本而不是按行号回源。

## 10. 本次实测（2026-11-03）

- 首轮 43 个文件 / 831 个 chunk（含 `docs/tasks/` 任务档案）
- 排除 `docs/tasks/`、补上 knowledge-mcp 自身文档后：**38 个文件 / 约 800 个 chunk**
- 全量构建 **约 50 秒**（本地 bge 冷启动；模型热后约 32 秒）
- 首次检索约 1.08 秒（模型加载）；后续查询待补测
- `mcp` 1.30.0，`FastMCP` 工具列表：`search_knowledge` / `read_knowledge` / `knowledge_stats`
- MCP stdio 冒烟：`initialize` → `list_tools` → `search` → `read` → `stats` 全通过
- `search "scheduler 为什么独立进程"` 第 1 条为 `comic-scheduler/README.md`
  的“为什么独立成进程”小节，`read` 返回命中 section 自身
- 20 条黄金问题 **Recall@5 = 20/20**，但 top-1 有 2 条不理想（见 `EVAL.md`）

## 10.1 `docs/tasks/` 是任务档案，不是知识

`docs/tasks/_template/01-brief.md` 这类文件会把“管理台任务记录在哪个表”带到
模板正文上。第一版用 `EXCLUDE_PREFIXES = ("docs/tasks/",)` 排除整个目录；
需求归档要查应该用专门的检索，而不是项目知识库。

## 11. 阈值与后续调优

`MIN_SCORE` 默认 0.45，是经验值，不是实测最优。第一版先保证“能查到”，
后续用 `EVAL.md` 的 20+ 条黄金问题跑 Recall@5，再决定：

- 阈值 0.40 / 0.45 / 0.50；
- 标题加权 0.08 / 0.12 / 0.16；
- 是否给 `module_notes` 降权；
- 是否对 `docs/architecture.md` 之外的历史稿做过滤。

## 12. 不要把代码塞进向量库

代码的强项是精确符号匹配。第一版只索引文档 / schema / OpenAPI；
“某个函数在哪”应该用 `ripgrep` 或 AST 符号索引，不要用 bge 语义检索硬找。

## 13. P0：read 契约、stale、错误语义（2026-11-03）

### 13.1 `CHUNKER_VERSION` 升到 2

v1 的 Markdown chunk 没有 `read_mode="lines"`，`read` 会退回 child chunk；
v1 还把“回读父小节”实现成“回溯到 H2”，遇到只有引子的 H2 就只剩标题。

v2 改成：

- Markdown/SQL chunk 带 `read_mode="lines"`；
- `read_knowledge` 回读 **section 自身**（`parent_start/end` 就是 section 行号）；
- 集合名随版本变成 `project_kb_61e9b771`，旧 `project_kb_c9378e7a` 保留但不使用。

**教训**：改“读法”也是改索引契约，不能只重建数据不升版本。

### 13.2 stale 检测

`manifest.json` 早就存了 sha1/mtime，但之前没有任何代码对比。现在：

- `indexer.check_stale()` 对比当前文件与 manifest；
- `bash scripts/dev.sh knowledge-index --check` 只检查、不重建，stale 时 exit 1；
- `knowledge_stats` 返回 `stale`、`stale_reasons`、`changed/new/missing` 计数。

### 13.3 `knowledge_stats` 摘要化

之前把完整 manifest（38 个文件的 sha1）塞回 Agent，token 浪费很大。
现在默认只返回 counts / built_at / stale；需要完整 manifest 时传 `detail=true`。

### 13.4 索引缺失/为空 / 版本不匹配 → ToolError

之前 `get_store()` 会创建空集合，`search` 返回 `hits: []`，Agent 会误以为
“知识库里没有”。现在 `ensure_ready()` 检查 manifest、collection、chunker_version、
真实条数；失败抛 `KnowledgeIndexError`，`server.py` 转成 `ToolError`，
MCP 客户端看到 `isError=true`。

### 13.5 已知副作用：自文档示例会污染检索

`knowledge-mcp/README.md` 里的查询示例包含真实问题词，重新索引后可能排到
`comic-scheduler/README.md` 前面。README 示例已改成 `<用户问题>` 占位符；
如果以后再加示例，**不要写会与真实问题重合的原句**。

## 14. message 数据源（2026-11-03）

### 14.1 接口，不是直连库

api 新增：

```text
GET /api/internal/knowledge/messages?cursor=&limit=
X-Service-Token: <HMAC>
```

- 全量 message 行，按 `id` 升序，不做收件范围过滤；
- 路由只允许 `require_service`，不接受用户 JWT；
- 增量游标 = `id > last_id`（message 表是追加式，没有 updated_at）；
- `toUserId` / `minRole` 返回给 indexer，但索引只把 `targeted`（0/1）放进 metadata，
  不把收件人写进正文。

### 14.2 集合与 manifest

- 集合：`project_kb_message_f0493561`（当前 12 条；与文档 `project_kb_61e9b771` 分开）；
- manifest：`crawler-service/data/project_rag/message_manifest.json`；
- MCP 工具：`search_messages` / `read_message` / `message_stats`。

### 14.3 实测

- 内部接口 12 条，`nextCursor=25`；
- 全量建索引约 3.2 秒（bge 冷启动）；增量无新消息 2.7 秒（主要是进程/模型加载）；
- 搜索热态约 11ms，冷态首次可能 3 秒以上；
- 增量游标停在 25；重复跑 `message-index` 不会重复插入（upsert）。

### 14.4 还没做

- **定时**：目前手动 `bash scripts/dev.sh message-index`；
- **purge 对账**：`--full` 会删本地集合重建，但还没有“只删已 purge 行”的增量对账；
- message 没有 `updated_at`，正文若被原地修改（正常业务不会），只有 `--full` 能发现；
- 全量消息含定向/管理员内容，MCP 是本地只读工具；如果以后对外，必须先加行级权限过滤。

## 15. 外部文档源（阶段一：Word / Excel / Markdown，2026-11-06）

### 15.1 为什么 Word 先转 Markdown，而不是另写一套切分

切分策略（标题树 + 代码块/表格原子化 + 480 token 复核）只有一套，且已经按细节调过。
Word 先归一成 Markdown，就能直接复用 `chunker.chunk_markdown`；给 docx 单写一套分块，
等于维护两套 bug。转换时**必须按 `body` 子元素顺序遍历**：`doc.paragraphs` 与 `doc.tables`
是两个独立列表，分开遍历会把所有表格挪到文末，破坏「这段文字说的是上面那张表」的上下文。

### 15.2 为什么 Excel 一行一个 chunk，且表头必须拼进每一行

一行是一条独立事实（一个员工、一条配置、一个物料）。整张表当一个 chunk 有两个问题：
① 超过 512 token 会被模型静默截断（见 §1）；② 检索命中「表」而不是「那一行」，答案里给不出具体值。
表头不拼进去，单看「张三 | 3500」不知道 3500 是什么；拼成「姓名：张三 ⏎ 工资：3500」才有意义。

### 15.3 二进制格式只能 `read_mode="chunk"`

`read_knowledge` 的 `lines` 模式是按行号回读**磁盘上的原文件**（`retriever._load_from_file`
还限定后缀 `{".md", ".sql", ".json"}`）。docx / xlsx 是二进制，Word 转换出的中间 Markdown
在磁盘上并不存在，所以这两类标 `chunk`，只回命中的那条 chunk —— 这是**有意接受的限制**，
不是遗漏。要整节原文得看原文件。

### 15.4 受限会话（DSH 沙箱）里装依赖：三条网络栈全被拒

`pip install python-docx openpyxl` 失败，逐层排查结论：

| 尝试 | 结果 |
|---|---|
| `pip install`（系统 TEMP） | `Permission denied` 于 pip 自己的 `pip-unpack-*/*.whl` |
| `pip install`（TMP 指到项目内） | 同样失败；新建目录也会被自动加上 `Everyone: DeleteSubdirectoriesAndFiles = Deny` 的 ACL |
| `curl.exe` 下载 | `schannel: AcquireCredentialsHandle failed: SEC_E_NO_CREDENTIALS`（与 git 早期同源） |
| `Invoke-WebRequest`（显式 TLS 1.2） | 基础连接被关闭 |
| **最终方案** | 三个包都是**纯 Python**，直接从 DSH 运行时的 `site-packages` 复制进 `crawler-service/.venv`（同为 CPython 3.13 / Windows x64），`requirements.txt` 仍按正常写法声明 |

> 换句话说：受限会话里**只有 harness 自己的 `web_fetch` 和 `git -c http.sslBackend=openssl` 能出网**；
> 普通终端不受此限，正常 `pip install -r requirements.txt` 即可。

### 15.5 受限会话里 `tempfile` 的两个坑（写单测必看）

1. `tempfile.TemporaryDirectory()` 退出时会 `chmod` 复核目录，报 `WinError 5` ——
   **断言全过却标记 error**，看起来像测试挂了；
2. `tempfile.mkdtemp()` 建出的目录（`0o700`）里**不允许再建子目录**，`Path.mkdir()` 直接拒绝访问。

`tests/test_external.py` 的 `_tmpdir()` 因此改成「自己命名 + `makedirs` + `rmtree(ignore_errors=True)`」。
既有 `test_corpus.py` / `test_indexer.py` 仍用 `TemporaryDirectory`，在受限会话里会有
5 个 `PermissionError`（与代码无关，普通终端跑是全绿）。

### 15.6 本次改动与实测

- 新增 `external.py`（解析 + 切分）；`chunker.chunk_markdown` 增加 `read_mode` 参数；
  `corpus.load_corpus()` 追加外部源；`CHUNKER_VERSION` 2 → 3。
- 集合指纹随之变化：`project_kb_61e9b771` → `project_kb_498e3b01`（旧集合保留，重建即生效）。
- 回归实测：原有语料仍为 **38 文件 / 816 chunk / 0 skipped**；三种格式各造一份真实文件后，
  Word 保留标题层级与 Markdown 表格、Excel 两行各一条（表头已拼入且空行跳过）、
  Markdown 走 `lines` 回读，合计 4 条 chunk、无 skip。

### 15.7 还没做

- PDF / HTML / PPT：加格式的顺序应是「先写解析器 → 再进 `config.EXTERNAL_SUFFIXES`」；
- Word / Excel 的 section 级回读（思路：转换结果落 sidecar `.md`，`read_mode` 复用 `lines`）；
- 增量索引：现在仍是全量重建，manifest 已按文件记 sha1，具备做增量的基础。

## 16. 分词器可切换（bigram ↔ jieba，2026-11-06）

### 16.1 为什么单独抽一层

原来切词逻辑长在 `retriever._lexical_tokens` 里，只服务「标题/正文加权」。阶段二要接
BM25，它同样需要切词，而且是**另一套口径**（BM25 要**词频**，加权只要**命中比例**）。
两处各写一份必然漂移：加权说命中、BM25 说没命中。所以抽出 `tokenizer.py` 作为唯一来源：

- `tokens()`：保留重复 → BM25 用；
- `unique_tokens()`：去重 → 加权用（原来的行为）。

### 16.2 沙箱里装不上 jieba（结论：代码先落地，装上即生效）

| 尝试 | 结果 |
|---|---|
| `pip install jieba` | 与 python-docx 同样的临时目录 ACL 问题（见 §15.4） |
| `git clone https://github.com/fxsjy/jieba.git`（openssl 后端） | 先 `Connection was reset`，再 `443 超时` —— 本会话早期能拉 GitHub，后期不再可达 |
| 全盘搜索已有 jieba | 无（含 DSH 运行时、workbuddy binaries、pip/npm 缓存） |
| **落地方式** | `COMIC_KB_TOKENIZER=auto` 默认值：代码现在就位，**装了 jieba 启动即自动切换**；缺包时退回 bigram |

显式写 `COMIC_KB_TOKENIZER=jieba` 而没装包时会**直接抛错**（附 pip 命令），
不静默降级 —— 否则会有人对着「换了分词器效果没变」排查半天（与 §embeddings 同一条原则）。

### 16.3 两个实现细节

- **懒加载**：`import jieba` + 建前缀词典约 1 秒 / 几十 MB，放在首次调用时做，拖慢 MCP
  进程启动不值当。
- **缓存目录改到项目内**（`INDEX_DIR.parent/tmp/jieba.cache`）：jieba 默认写系统临时目录，
  受限会话里不可写，会导致每次启动都重建前缀词典。
- 用户词典**自己解析**再逐词 `add_word`，不用 `load_userdict`：后者对各版本 `#` 注释的
  容错不一致，而且坏行不告诉你是哪一行。

### 16.4 换分词器必须重标（尚未做，等 jieba 装上）

`EVAL.md` 的 **20 条黄金问题 Recall@5 = 100%** 是 **bigram 基线**。换成 jieba 后：

1. 重跑评估集，确认不回退；
2. 重标 BM25 的 `min_score`（绝对分会整体缩小：实测同一篇 d1 从 3.058 → 1.050）；
3. 复核 `retriever` 的 boost 上限（0.12 / 0.08）—— 分母 `len(tokens)` 变小，命中比例会更大。

**没做这三步就等于没换成功**：分数变了、曲线没测，只能算"改了代码"。

## 17. 阶段二：BM25 + RRF 接入实测（2026-11-06）

### 17.1 改动

- 新增 `lexical.py`（内存 BM25，从 Chroma 现读文档，`invalidate()` 与 `build_index()` 联动）；
- `retriever.search()` 改为双路 + RRF，新增 `mode`（`hybrid` / `vector` / `lexical`）；
- `_hit()` 增加 `sources` / `rrf` / `lexical_score` / `matched_terms`；
- `config` 增加 `LEXICAL_TOP_K` / `LEXICAL_K1` / `LEXICAL_B` / `HYBRID_ENABLED` / `RRF_K`；
- `indexer` 增加 `all_documents()` / `documents_by_ids()`（都**不构造 embedding**）。

### 17.2 效果（标准答案来自「单词在哪些 .md 里真实出现」）

| 查询 | 纯向量 | 混合 | 说明 |
|---|---|---|---|
| `X-Service-Token` | **top-10 全是 openapi.json，一条都不对** | **第 1 名正确**（api-service/README） | 专有名词只有词面能捞到 |
| `COMIC_KB_TOKENIZER` | top-10 无正确项 | **第 2 名正确**（knowledge-mcp/README） | 同上，且向量被「openapi 参数」吸走 |
| `hnsw:space` | 第 1 名正确 | 第 1 名正确 | 回归：没有把对的挤下去 |

评估集（20 条）：`vector` 20/20、`hybrid` 20/20、`lexical` 18/20 —— **混合没让任何一条变差**，
纯词面单独用会漏两条（语义类问题它本来就答不了）。

延迟（模型热态）：`vector` 18~20ms、`hybrid` 28~30ms —— 词面那路多约 **10ms**（833 篇、2 万词项）。

### 17.3 三个必须记住的坑

1. **`score` 的含义变了**。`vector` 模式是余弦（0~1），`hybrid` 是 RRF（约 0.016）。
   任何"按分数阈值判断"的旧代码在混合模式下都会失效 —— 要相似度请读 `vector_score`。
2. **RRF 会把平局留给你**。两路各自排第一的两条，融合分**完全相同**（`1/61`），
   排序退化成按 doc_id。这不是 bug，是"只合并不裁决"的本性 —— 该由 rerank（P2.3）或
   精确匹配规则来打破。
3. **索引新鲜度**。BM25 是从集合现读的，所以 `build_index()` 后必须 `invalidate()`；
   实测就中过一次：改完 README 没重建，`doctor` 报 833 chunk 而索引仍是 827，
   A/B 全在旧语料上跑 —— **先查 `doctor` 的 chunk 数再信任何对比**。

### 17.4 反例：混合把正确答案从第 2 名推到第 4 名（`同源判重键是什么`）

**不是所有查询混合都赢**，这条必须留档，否则会以为开了混合就万事大吉。

| 模式 | 正确答案（`crawler-service/README.md` / 约定）名次 |
|---|---|
| vector | 第 2（0.6114） |
| lexical | 前 5 没有 |
| **hybrid** | **第 4** ← 变差 |

根因是**疑问句式被两字滑窗切成了噪音词**：

```
"同源判重键是什么" → 同源 / 源判 / 判重 / 重键 / 键是 / 是什 / 什么
```

- `是什` 来自「…是**什**么」，出现在 **15 篇**里 → **IDF = 3.985**，
  与真词「判重」的 3.985 **完全相同**；
- 各模块 `NOTES.md` 的「条目模板」章节都写着「…是什么」，于是 `deploy/NOTES.md`、
  `scripts/NOTES.md`、`tools/NOTES.md` 一起被捞上来；
- 实测 `deploy/NOTES.md` 那条模板 chunk：命中词**只有** `是什`(tf=2) 和 `什么`(tf=5)，
  `同源` / `判重` **各出现 0 次**，却拿到 9.971 分 —— 零相关高分。

**对照实验**（去掉疑问尾巴名次立刻回来）：

| 查询 | 正确答案名次 |
|---|---|
| `同源判重键是什么` | 4 |
| `同源判重键` | **2** |
| `同源判重` | 3 |

**评估集仍是 20/20**，因为答案还在前 5 —— 这说明 **Recall@5 看不见排名退化**，
后续评估要补 MRR / nDCG。

结论：混合检索扩大能力面的同时也放大了噪音，所以「开关 + `sources`/`matched_terms` 观测 +
更细的评估指标 + rerank」缺一不可。修这个具体问题的正解是 **jieba**（真分词不会产出 `是什`）
与 **查询侧剥离疑问框架**（是什么 / 怎么 / 为什么）。

### 17.5 jieba 装上后的实测：修好一个、弄坏两个（2026-11-06）

jieba 0.42.1 最终装上了（GitHub 恢复后 `git clone` + 整目录复制进 `site-packages`；
pip 仍受临时目录 ACL 限制）。用户词典生效，`判重` 被保住成整词。

**索引层变化**（同一批 833 个 chunk）：

| | bigram | jieba |
|---|---|---|
| 词项数 | 20396 | **6466** |
| avgdl（平均文档词数） | 104.51 | **70.15** |

文档变短 → 长度归一与 IDF 分布都变了，**这是打分刻度变化，不是"更准"**。

**三个案例的净效果**：

| 案例 | bigram | jieba | 结论 |
|---|---|---|---|
| `同源判重键是什么`（正确答案名次） | 4 | **2** | ✅ 修好：`是什` 消失，模板文档不再被捞起 |
| `X-Service-Token`（正确答案名次） | **1** | 3 | ❌ 变差：query 词相同，但 doc 侧 tf/df/avgdl 全变，排序漂移 |
| `怎么新增一个爬虫源`（正确答案名次） | 5（勉强） | **掉出前 5** | ❌ 变差：bigram 靠碎片 `虫源` 侥幸命中；jieba 切成 `爬虫` 后**文档里没有这个词** |

补用户词典（`爬虫源`）**救不回来**——查询侧有了这个词，文档侧依然没有，匹配不上。
说明：**词典只能统一"切法"，不能凭空造出语料里不存在的词**。

**评估集（20 条）**：

| | vector | hybrid | lexical |
|---|---|---|---|
| bigram | 20/20 | **20/20** | 18/20 |
| jieba | 20/20 | **19/20** | 19/20 |

**结论**：两者是**取舍**不是升级——

- bigram：高召回、高噪音（碎片既可能救命 `虫源`，也可能下毒 `是什`）；
- jieba：高精度、会漏词（长尾词/新词切不出来，靠词典补）。

默认仍是 `auto`（有 jieba 即用 jieba），所以**装上之后线上行为已经变了**。要不要切回去，
由 `COMIC_KB_TOKENIZER=bigram|jieba` 一行决定。真正的下一步是**三路融合**（向量 + bigram +
jieba 各出一榜再 RRF），而不是在两种分词器里二选一 —— 那才是把"碎片召回"和"虚词噪音"
同时管住的办法。

### 17.6 `mixed` 后端（中英分流）与三组实测（2026-11-06）

**做法**：先用正则抓英文/数字标识符（`require_admin`、`X-Service-Token`），
**整体保留 + 按 `._-` 拆部件**；其余中文段交给 jieba。

```
X-Service-Token 怎么配        → x-service-token, service, token, 怎么
require_admin 是哪个装饰器     → require_admin, require, admin, 哪个, 装饰
同源判重键是什么               → 同源, 判重, 什么          （没有 是什）
```

**三组评估集（20 条，同一份索引）**：

| 后端 | vector | lexical | hybrid |
|---|---|---|---|
| `bigram` | 20/20 | 18/20 | **20/20** |
| `jieba` | 20/20 | 19/20 | 19/20 |
| `mixed` | 20/20 | 19/20 | **19/20** |

三组掉的是**同一条**：`怎么新增一个爬虫源`（bigram 靠碎片 `虫源` 侥幸命中，另两者丢）。

**为什么 mixed 没赢**（三条，都要记住）：

1. **中文段仍是 jieba** → 依赖碎片召回的题照样丢，`mixed` 只解决了英文侧；
2. **hybrid 的最终名次主要由向量那一路决定**，而向量那路三种分词**完全相同** ——
   词面的改善被稀释（`require_admin` 上 mixed 三个 token 全中，但 top1 分数只从
   0.0328 变 0.0325）；
3. **标识符整体化会摊薄单 chunk 的分**：同一文档多个小节都含 `X-Service-Token` 时，
   多个 chunk 同时高分、互相竞争，正确小节反而被挤出前 5。

**结论**：**分词器不是当前瓶颈**。三种切法在 hybrid 下的差别只落在 1 条边缘用例上。
真正的瓶颈是**单通道**——要么保碎片、要么保干净，二选一。正解是多通道融合：

```
向量 ──┐
bigram ─┼─→ RRF（三榜）──→ rerank ──→ top_k
mixed  ─┘
```

`mixed` 的代码保留（`COMIC_KB_TOKENIZER=mixed`），等标识符类查询变多时再评估。

### 17.7 决定：默认切到 `mixed`（2026-11-06）

`auto` 在有 jieba 时改为选 **`mixed`**，理由是它是 jieba 的**超集**：

- 中文切法完全相同（同一套词典 + 用户词典），所以 `同源判重键是什么` 那条修复照旧生效；
- 英文/数字标识符额外做到"整体 + 部件"双份，`require_admin` 这类查询三类 token 全中。

`bigram` 降级为**零依赖兜底**（没装 jieba 时 `auto` 才用它），不再作为并列选项。

**评估集维持 19/20**（hybrid），掉的那条 `怎么新增一个爬虫源` 经确认是**语料本身缺词**：
文档里写的是"源站 / 适配器"，没有"爬虫源"这个词；bigram 靠两字碎片 `虫源` 侥幸命中，
属于数据巧合而非切分能力。**接受这条损失**，不为它保留一条噪音通道。

验收三条（同一份索引，默认 mixed）：

| 查询 | 正确项名次 | 备注 |
|---|---|---|
| `同源判重键是什么` | **2**（原 bigram 下是 4） | `是什` 噪音消失 |
| `require_admin 是什么权限` | **1** | `require_admin` / `require` / `admin` 三词全中 |
| `定时任务三个文件谁写谁读` | **1** | 未回退 |
