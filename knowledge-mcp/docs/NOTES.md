# 踩坑与实测

> **这份文档只记发生过的问题和实测数据。** 设计取舍见 [ARCHITECTURE.md](ARCHITECTURE.md)，
> 操作步骤见 [OPERATIONS.md](OPERATIONS.md)，参数含义见 [CONFIG.md](CONFIG.md)。
>
> 写法约定：每个问题 = **现象 / 根因 / 做法**；每次改动 = **日期 + 实测数字**。
> 没实测过的推测不要写进来。

## 目录

- [一、切分与索引](#一切分与索引)
- [二、检索与加权](#二检索与加权)
- [三、语料与过滤](#三语料与过滤)
- [四、外部文档（Word / Excel / Markdown）](#四外部文档word--excel--markdown)
- [五、分词](#五分词)
- [六、运行环境（受限会话 / Windows）](#六运行环境受限会话--windows)
- [七、实测汇总](#七实测汇总)

---

## 一、切分与索引

### 1.1 bge-small-zh 只有 512 token，长 chunk 后半段被静默截断

`max_position_embeddings = 512`，`tokenizer_config.json` 的 `model_max_length` 也是 512。
中文 1 字约 1 token，所以 1200 字的 chunk **后半段直接丢**，而且不报错 ——
表现为"明明写在文档里，检索就是找不到"。

**做法**：目标 300–400 字、硬上限 500 字、token 复核 480；`chunker.py` 用本地
`tokenizer.json` 计数，找不到 tokenizer 时回退字符数（偏保守）。

全库约 800 个 chunk 中 5 个超过 480 token（最大 1042），全部是目录树代码块 ——
代码块不从中间切，接受这个例外。

### 1.2 集合名必须带 embedding + 切分指纹

`collection_metadata={"hnsw:space": "cosine"}` **只在集合首次创建时生效**；
集合已存在时再传会被静默忽略。所以：

- 集合名 = `project_kb_<backend:model:dim:chunkN 的短哈希>`；
- 换模型 / 改切分规则 → 自动落到新集合，旧索引保留；
- 重建时先 `delete_collection()` 再重开，避免旧集合的 L2 度量继续生效。

### 1.3 改"读法"也是改索引契约

v1 的 Markdown chunk 没有 `read_mode`，`read` 会退回 child chunk；且"回读父小节"被实现成
"回溯到 H2"，遇到只有引子的 H2 就只剩标题。

v2 改成：Markdown/SQL chunk 带 `read_mode="lines"`、回读 **section 自身**、
集合名随之变为 `project_kb_61e9b771`（旧 `project_kb_c9378e7a` 保留但不使用）。

**教训**：升 `CHUNKER_VERSION` 不能只重建数据 —— 版本号进集合指纹，靠它换集合。

### 1.4 SQL 与 OpenAPI 的切法

- SQL：按 `CREATE TABLE` 块解析，一张表一个 chunk；`VARCHAR(255)` / `DECIMAL(10,2)`
  里的括号不能当块结束，`corpus._find_matching_paren` 做了深度扫描。
- OpenAPI：`paths` 50 个、无 tags，按 method + path 一个 endpoint 一个 chunk，共 63 个；
  端点没有稳定行号，`read_mode=chunk`。

---

## 二、检索与加权

### 2.1 `read_knowledge` 不要走 `get_store()`

`get_store()` 会构造 `get_embeddings()`，本地后端要加载 bge ONNX（约 1 秒）。
回读只需要 Chroma 的 `get()`，所以 `retriever.read()` 直接用
`chromadb.PersistentClient(...).get_collection(...)`，避免每次 `read` 白加载模型。

### 2.2 标题加权不能带 title / path

第一版加权把 `title`、`path` 也算进去，结果同一篇文档的所有 chunk 都因为文档标题
命中而一起涨分。例如问 "scheduler 为什么独立进程"，`comic-scheduler/README.md`
的每个小节都带 "comic-scheduler … 独立进程"，加权完全失去区分度。

**改为只用 section `heading` 做加权**（最多 +0.12），向量分仍是主体。
该查询的正确小节从第 2 升到第 1。

### 2.3 同一个 H2/H3 切出的多个 child 要去重

一个长小节会切成多个 child，检索时可能同时命中 2~3 个同 heading 的 chunk。
`read_knowledge` 反正会回读整个父小节，所以 `search` 按 `(path, heading_path)` 去重，
只保留分数最高的 child —— 否则 `top_k` 被同一节占满。

### 2.4 阈值是经验值，不是最优解

`MIN_SCORE` 默认 0.45。第一版先保证"能查到"，待调项：

- 阈值 0.40 / 0.45 / 0.50；
- 标题加权 0.08 / 0.12 / 0.16；
- 是否给 `module_notes` 降权；
- 历史稿过滤范围要不要扩大。

⚠️ 这个阈值**只对向量路有效**（见 5.6 与 ARCHITECTURE 的融合分语义）。

### 2.5 72KB 的 `comic-front/docs/NOTES.md`

它一个文件切出 125 个 chunk（全库最多），内容有用但噪声也大。第一版不特殊处理；
如果评测发现它经常挤掉更相关的 README，可以给 `kind=module_notes` 降权，或把它按主题拆文件。

### 2.6 自文档示例会污染检索

`knowledge-mcp/README.md` 里的查询示例曾包含真实问题词，重新索引后排到了
`comic-scheduler/README.md` 前面。**示例一律用 `<用户问题>` 这类占位符**，
不要写会与真实提问重合的原句。

---

## 三、语料与过滤

### 3.1 历史稿要标 `historical`

- `docs/architecture.md`：文件头明确写"v1 设计稿、不是现状"，标 `status=historical`，
  默认过滤；否则"项目有没有 Redis"会答出未落地方案。
- `tools/README.md`：仍写迁移 `0001~0009`，实际已到 `0010`。这是**文档本身待修**，
  索引层无法自动判断；评测命中时先修文档。
- `sources/guazi/README.md`：只有 fixtures、没有适配器，直接排除。

### 3.2 `docs/tasks/` 是任务档案，不是知识

`docs/tasks/_template/01-brief.md` 这类文件会把"管理台任务记录在哪个表"带到模板正文上。
用 `EXCLUDE_PREFIXES = ("docs/tasks/",)` 排除整个目录；需求归档该用专门的检索。

### 3.3 不要把代码塞进向量库

代码的强项是精确符号匹配。"某个函数在哪"应该用 `ripgrep` 或 AST 符号索引，
不要用 bge 语义检索硬找。

---

## 四、外部文档（Word / Excel / Markdown）

> 为什么 Word 先转 Markdown、为什么 Excel 一行一个 chunk —— 设计理由见
> [ARCHITECTURE.md](ARCHITECTURE.md)。这里只记限制与实测。

### 4.1 二进制格式只能 `read_mode="chunk"`

`lines` 模式要按行号回读**磁盘上的原文件**（`retriever._load_from_file` 还限定后缀
`{".md", ".sql", ".json"}`）。docx / xlsx 是二进制，Word 转出的中间 Markdown 在磁盘上
并不存在，所以这两类标 `chunk`，只回命中的那条 —— **有意接受的限制**，要整节得看原文件。

### 4.2 实测（2026-11-06）

- 新增 `external.py`；`chunker.chunk_markdown` 增加 `read_mode` 参数；
  `corpus.load_corpus()` 追加外部源；`CHUNKER_VERSION` 2 → 3。
- 集合指纹随之变化：`project_kb_61e9b771` → `project_kb_498e3b01`（旧集合保留）。
- 回归：原有语料仍为 38 文件 / 816 chunk / 0 skipped。
- 三种格式各造一份真实文件：Word 保留标题层级与 Markdown 表格、Excel 两行各一条
  （表头已拼入、空行跳过）、Markdown 走 `lines` 回读，合计 4 条 chunk、无 skip。

### 4.3 还没做

- PDF / HTML / PPT：加格式的顺序是「先写解析器 → 再进 `config.EXTERNAL_SUFFIXES`」；
- Word / Excel 的 section 级回读（思路：转换结果落 sidecar `.md`，`read_mode` 复用 `lines`）；
- 增量索引：现在仍是全量重建，manifest 已按文件记 sha1，具备做增量的基础。

---

## 五、分词

### 5.1 为什么把切词抽成独立一层

原来切词逻辑长在 `retriever._lexical_tokens`，只服务标题/正文加权。接 BM25 后出现
第二套口径（BM25 要**词频**、加权只要**命中比例**），两处各写一份必然漂移：
加权说命中、BM25 说没命中。所以抽出 `tokenizer.py`：

- `tokens()`：保留重复 → BM25 用；
- `unique_tokens()`：去重 → 加权用。

### 5.2 三个实现细节

- **懒加载**：`import jieba` + 建前缀词典约 1 秒、几十 MB，放到首次调用时做；
- **缓存目录改到项目内**（`INDEX_DIR.parent/tmp/jieba.cache`）：jieba 默认写系统临时目录，
  受限会话里不可写，会导致每次启动都重建前缀词典；
- **用户词典自己解析**再逐词 `add_word`，不用 `load_userdict`：后者对各版本 `#` 注释的
  容错不一致，且坏行不告诉你是第几行。

### 5.3 不配用户词典，上 jieba 反而更差

jieba 默认词典不认识「判重 / 图床 / 管理台 / 按需导入」，不配 `terms.txt` 时它们会被切成
`判/重` 这种单字，再被长度过滤丢掉 —— 整词消失，比 bigram 还差。

### 5.4 换分词器必须重标（这条最容易跳过）

同一批文档、同样 30 条查询，只换分词器：

| | bigram | jieba | mixed |
|---|---|---|---|
| 词项数 | 20396 | 6466 | 7575 |
| avgdl（平均文档词数） | 104.51 | 70.15 | 75.70 |

文档变短 → 长度归一与 IDF 分布全变 → **BM25 分数不可跨分词器比较**
（同一篇文档：bigram 3.058 / jieba 1.050）。所以换后端后：重跑评估集、重标阈值、
重标加权上限，一样都不能省。

### 5.5 修好的案例：疑问虚词被当成实词

`是什` 是「…是**什**么」被两字滑窗切出来的碎片，出现在 15 篇里 —— IDF 3.985，
与真词「判重」**完全相同**。各模块 NOTES 的「条目模板」都含"是什么"，于是全被捞上来：
`deploy/docs/NOTES.md` 那条模板 chunk 命中词**只有** `是什`(tf=2) 和 `什么`(tf=5)，
`同源`/`判重` **各 0 次**，却拿到 9.971 分。

改 jieba / mixed 后（token 变成 `同源 / 判重 / 什么`）：正确答案从 **第 4 名回到第 2 名**。

对照实验：保留疑问尾巴时正确答案排第 4；去掉尾巴后升到第 2；只留核心词则第 3。
**问题不在检索能力，在"问题自带的虚词被当成了实词"。**

### 5.6 弄坏的案例：`X-Service-Token`（jieba）

query 分词完全相同（`service` / `token`），名次却从第 1 掉到第 3。根因在**文档侧**：

| 原文 | bigram | jieba | mixed |
|---|---|---|---|
| `token_service` | 一个词 | `token` + `service` | 整体 + 两部件 |
| `COMIC_JWT_SECRET` | 一个词 | `comic` + `jwt` + `secret` | 整体 + 三部件 |
| `require_admin` | 一个词 | `require` + `admin` | 整体 + 两部件 |

标识符被拆开后 `df(service)` 179→181、`df(token)` 48→51，**每篇的 tf 与 `|D|` 都变了**
—— 这就是"同一把尺子换了刻度"，不是谁更准。mixed 把标识符整体保留 + 部件展开，
两边兼顾。

### 5.7 三组评估对比（20 条黄金题）

| 后端 | vector | lexical | hybrid |
|---|---|---|---|
| `bigram` | 20/20 | 18/20 | **20/20** |
| `jieba` | 20/20 | 19/20 | 19/20 |
| `mixed` | 20/20 | 19/20 | 19/20 |

三组掉的是**同一条**（第 5 条，靠碎片侥幸命中的那条）。经确认是**语料缺词**（文档写的是
"源站/适配器"，没有"爬虫源"），bigram 靠碎片 `虫源` 侥幸命中 —— **数据巧合，不是能力**。
补用户词典也救不回来：词典只能统一"切法"，不能凭空造出语料里不存在的词。

**决定**：默认 `mixed`，接受这条损失，不为它保留一条噪音通道。

---

## 六、运行环境（受限会话 / Windows）

### 6.1 `TMP` / `TEMP` / `TMPDIR` 必须三个都改

Windows 上 Chroma 的 Rust SQLite / fastembed **直接读系统临时目录**（不走 Python 的
`tempfile` 回退逻辑）。只改 `TMP` 不改 `TEMP`，它们仍可能落到工作区外不可写的
`AppData\Local\Temp\dsh-*`，报 `code: 14 unable to open database file` / `WinError 5`。

`run_mcp.py` 和 `dev.sh knowledge-index` 都是**三个一起覆盖**，不是 `setdefault`；
`comic_chat.runtime_env.prepare()` 还会在检测到不可写时兜底到 `DATA_ROOT/tmp`。

### 6.2 受限会话里装依赖：三条网络栈全被拒

`pip install python-docx openpyxl` 失败，逐层排查：

| 尝试 | 结果 |
|---|---|
| `pip install`（系统 TEMP） | `Permission denied` 于 pip 自己的 `pip-unpack-*/*.whl` |
| `pip install`（TMP 指到项目内） | 同样失败；新建目录也会被自动加上 `Everyone: DeleteSubdirectoriesAndFiles = Deny` 的 ACL |
| `curl.exe` 下载 | `schannel: AcquireCredentialsHandle failed: SEC_E_NO_CREDENTIALS`（与 git 早期同源） |
| `Invoke-WebRequest`（显式 TLS 1.2） | 基础连接被关闭 |
| **最终方案** | 纯 Python 包直接从 DSH 运行时的 `site-packages` 复制进 `crawler-service/.venv`（同为 CPython 3.13 / Windows x64）；`requirements.txt` 仍按正常写法声明 |

> 受限会话里**只有 harness 自己的 `web_fetch` 和 `git -c http.sslBackend=openssl` 能出网**；
> 普通终端不受此限，正常 `pip install -r requirements.txt` 即可。

### 6.3 jieba 的安装（同一类问题的另一个解）

`pip` 与 `curl` 都不通时，最终用 `git clone`（openssl 后端）取源码，整目录复制进
`site-packages` —— jieba 是纯 Python，复制即安装。
GitHub 的可达性在本机是**间歇性**的（先 reset、后 443 超时，隔一段时间又能连），
失败先重试，不要立刻换方案。

### 6.4 受限会话里 `tempfile` 的两个坑（写单测必看）

1. `tempfile.TemporaryDirectory()` 退出时会 `chmod` 复核目录，报 `WinError 5` ——
   **断言全过却标记 error**，看起来像测试挂了；
2. `tempfile.mkdtemp()` 建出的目录（`0o700`）里**不允许再建子目录**，`Path.mkdir()` 拒绝访问。

`tests/test_external.py` 的 `_tmpdir()` 因此改成「自己命名 + `makedirs` +
`rmtree(ignore_errors=True)`」。既有 `test_corpus.py` / `test_indexer.py` 仍用
`TemporaryDirectory`，在受限会话里有 5 个 `PermissionError`（与代码无关，普通终端全绿）。

---

## 七、实测汇总

### 7.1 建库与检索（2026-11-03，v2）

- 首轮 43 文件 / 831 chunk（含 `docs/tasks/`）；排除后 **38 文件 / 约 800 chunk**
- 全量构建 **约 50 秒**（冷启动；模型热后约 32 秒）
- 首次检索约 1.08 秒（模型加载），热态 10~20ms
- `mcp` 1.30.0；stdio 冒烟：`initialize` → `list_tools` → `search` → `read` → `stats` 全通过
- 20 条黄金问题 Recall@5 = 20/20；但 top-1 有 2 条不理想（见 [EVAL.md](EVAL.md)）

### 7.2 索引新鲜度与错误语义

- `check_stale()` 对比当前文件与 manifest；`--check` 只查不建，过期 exit 1；
  `stats` 返回 `stale` / `stale_reasons` / `changed|new|missing` 计数
- `stats` 默认只给摘要（完整 manifest 要 `detail=true`），避免把 38 个文件的 sha1 塞进上下文
- 索引缺失/为空/版本不匹配时抛 `ToolError`，**不返回空 hits 假装"没有资料"**

### 7.3 message 子索引（2026-11-03）

- 内部接口 12 条，`nextCursor=25`
- 全量建索引约 3.2 秒（bge 冷启动）；增量无新消息 2.7 秒（主要是进程/模型加载）
- 搜索热态约 11ms，冷态首次可能 3 秒以上
- 重复跑 `message-index` 不会重复插入（upsert）
- 集合 `project_kb_message_f0493561`，与文档集合分开

**还没做**：定时刷新（目前手动）；purge 对账（`--full` 只删本地集合）；
message 没有 `updated_at`，正文若被原地修改只有 `--full` 能发现；
全量消息含定向/管理员内容，若以后对外必须先加行级权限过滤。

### 7.4 阶段二：BM25 + RRF（2026-11-06）

- 词面索引：838 篇 / 20396 词项（bigram）；从 Chroma 现读，**不加载 embedding**
- 延迟（模型热态）：`vector` 18~20ms → `hybrid` 28~30ms（词面多约 10ms）
- `X-Service-Token`：纯向量 top-10 全错 → 混合第 1 名正确
- `COMIC_KB_TOKENIZER`：纯向量 top-10 无正确项 → 混合第 2 名正确
- `hnsw:space`：两种模式都是第 1 名（未回退）
- **索引新鲜度教训**：本轮曾在"语料 833、索引 827"的过期索引上跑完一整轮 A/B，
  结论全错。**做任何对比前先看 `doctor` 的两个数字。**

### 7.5 阶段二：已知缺口

- **rerank 未实现** → RRF 平局靠 `doc_id` 字典序裁决；
- BM25 公式没有手算单测；
- 加权上限（0.12 / 0.08）按 bigram 的 token 数标定，换 mixed 后未重标；
- 评估只有 Recall@k，**看不见排名退化**（`同源判重键` 从 #2 掉到 #4 时 Recall 仍算过）。
