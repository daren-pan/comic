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

### 1.5 按行打包会产生"半句话碎块"（2026-11-07 发现，当日修复）

**现象**：`comic-scheduler/README.md › 每一轮都进任务表` 被切成 206 / 467 / **36** 三块，
最后一块只有一句「`Duplicate entry`，且它的收尾会**覆盖第一轮的行**。」，
单独拿出来完全看不出在讲什么。

**根因**：`_split_block` 处理超长段落时**按行累加**，而中文文档普遍按 60 字手工折行 ——
换行不是语义边界，切点于是落在半句话中间。

```
段落 506 字
  逐行累加到第 8 行 = 467 字
  再加最后一行（39 字）= 506 > 500  → 在这里断
  产出 [467, 38]，38 字那块 strip 后成 36 字
  装箱时前后都装不下，也不再合并 → 碎块进索引
```

**关键验证**：用 LangChain `RecursiveCharacterTextSplitter` 的**默认分隔符**
（`["\n\n", "\n", " ", ""]`）跑同一段文本，结果也是 `[467, 36]` ——
**问题不在实现，在"把换行当分隔符"这件事本身**。

**修复**（`CHUNKER_VERSION` 3 → 4）：改用 LangChain 递归切分，分隔符按语义排列
`["\n\n", "。", "！", "？", "；", "\n", " ", ""]`，句号排在换行前面。

| | 改前（按行） | 改后（句子优先） |
|---|---|---|
| 那个例子 | `[206, 467, 36]` | `[206, 346, 159]` |
| 全库块数（markdown 部分） | 810 | 812 |
| < 120 字的块 | 68 | 67 |
| **真残余（句子被切断）** | **9** | **6** |

**顺带发现**：68 个碎块里只有 9 个是"被切断的句子"，其余是本来就短的内容
（短段落、表格行、单句小节）—— **不该合并**。所以只修切分、不做尾块合并。

**评估影响**（20 条黄金题，**当时的基线是 `k=60` 等权 + BM25 `1.5/0.75`**）：
vector 与 hybrid 持平或略升（vector 20/20、MRR 0.825；hybrid MRR 0.764 → 0.771），
**lexical 从 19/20 降到 17/20** —— 掉的两条
（`<术语>是什么` / `<功能>记录在哪个表` 这两类问法）是**自文档污染**：
块变紧后，`NOTES.md` 里"讲知识库自身"的小节 BM25 分数更高，抢到了前排。
这是既有的污染问题被放大，不是切分质量退化（见 2.6 / 7.6）。

> 2026-11-08 追记：后续调了 BM25（`1.8/0.9`）和 RRF（`k=3`、`0.75/0.25`），
> 这两条已回到正确位置（字面 19/20 → 现在 18/20 但 MRR 0.710，混合 Top-1 90%）。
> 上面这行数字只代表 11-07 那天的状态。

**遗留**：`CHUNKER_VERSION` 变更会让集合名变化，旧集合不会被自动删除
（实测索引目录里已堆到 5 个集合 / 47 MB）。

### 1.7 ⚠️ 增量索引曾经是坏的：什么都不改也要重算一半

**现象**：只改了两三个文档，`kb index` 却报「新增 430 / 删除 429 / 跳过 484」，耗时 26 秒；
更离谱的是**什么都不改**再跑一遍，仍然是「新增 421 / 删除 421」。

**根因**：LangChain `index(cleanup="incremental")` 的清理是**按批次**做的 ——
每批写完就对该批出现的源文件执行「删掉更新时间早于本轮开始的记录」。
一个文件的分块如果跨了两个批次（`comic-front/docs/NOTES.md` 有 125 块，默认批次 32），
第 1 批处理完就把这个文件**还没轮到**的块当成过期删掉，后面几批再补回来 —— 于是每次都churn。

**修复**：把批次调成「一次装下整个语料」（上限 4096 块），清理只在最后跑一次。

| 场景 | 修复前 | 修复后 |
|---|---|---|
| 什么都没改 | 26 秒，新增 421 / 删除 421 | **1.3 秒，新增 0 / 删除 0 / 跳过 914** |
| 改一个小文件 | — | **1.4 秒，新增 1 / 删除 1** |

> 教训：**"用了标准组件"不等于"行为符合直觉"**。LangChain 的 docstring 里其实写了
> "同一 source 跨批次会做冗余工作"，但那句话读起来像"稍微慢一点"，实际是**反复删了重建**。

---

## 二、检索与加权

### 2.1 `read_knowledge` 不要走 `get_store()`

`get_store()` 会构造 `get_embeddings()`，本地后端要加载 bge ONNX（约 1 秒）。
回读只需要 Chroma 的 `get()`，所以 `retriever.read()` 直接用
`chromadb.PersistentClient(...).get_collection(...)`，避免每次 `read` 白加载模型。

### 2.2 标题加权不能带 title / path

第一版加权把 `title`、`path` 也算进去，结果同一篇文档的所有 chunk 都因为文档标题
命中而一起涨分。例如问「某模块为什么独立进程」，该模块 README 的每个小节都带
"<模块名> … 独立进程"，加权完全失去区分度。

**改为只用 section `heading` 做加权**（最多 +0.12），向量分仍是主体。
该查询的正确小节从第 2 升到第 1。

> 2026-11-08 追记：标题/正文加权后来整组移除，只保留"模块 +0.06"，见 ARCHITECTURE。

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

### 2.7 重排实测：`bge-reranker-v2-m3` 帮了混合、伤了语义（2026-11-08）

**背景**：混合检索 Top-1 只有 65%，怀疑"RRF 只合并不裁决"是瓶颈，于是接标准重排：
`CrossEncoderReranker` + `HuggingFaceCrossEncoder` + `BAAI/bge-reranker-v2-m3`（2.1 GB）。

**结果**（20 条黄金题，top_k=5，重排 10 条候选）：

| 模式 | 不重排 | 重排后 | 结论 |
|---|---|---|---|
| 语义检索 | 20/20 · MRR 0.950 · nDCG 0.982 · **Top-1 90%** | 20/20 · 0.812 · 0.897 · **Top-1 70%** | **明显变差** |
| 混合检索 | 20/20 · 0.781 · 0.919 · **Top-1 65%** | 20/20 · 0.818 · 0.907 · **Top-1 70%** | Top-1 +5pt，nDCG −0.012 |

**为什么语义反而变差**：交叉编码器读的是"文档和问题像不像"，而 `NOTES.md` 里
"举例引用问题原句"的段落**跟问题字面最像** —— 它把自文档污染**放大**了，不是修复。
例：某个专名查询重排后，第一名变成了"讲这个术语"的案例段，而不是定义它的章节。

**成本**：CPU 上 10 条候选约 **7 秒**（检索本身 50 ms），慢 140 倍。

**结论**：默认**关闭**（`COMIC_RAG_RERANK` 不设）。要用得先解决下面之一：
① 把"讲知识库自身"的段落排除出重排候选；② 重排分与融合分加权而不是完全替换；
③ 换更小更快的模型（ONNX 量化版）。

**接线时的两个坑**：

1. `CrossEncoderReranker` 的 `model` 必须是 LangChain 的 `BaseCrossEncoder`
   （用 `HuggingFaceCrossEncoder` 包一层）；直接传 sentence-transformers 的
   `CrossEncoder` 会被 pydantic 校验拒掉。
2. `CrossEncoderReranker.compress_documents()` **只返回排好序的 Document、不返回分数**；
   要分数得自己调 `compressor.model.score(pairs)`。

---

## 三、语料与过滤

### 3.1 历史稿要标 `historical`

- `docs/architecture.md`：文件头明确写"v1 设计稿、不是现状"，标 `status=historical`，
  默认过滤；否则"项目有没有 Redis"会答出未落地方案。
- `tools/README.md`：仍写迁移 `0001~0009`，实际已到 `0010`。这是**文档本身待修**，
  索引层无法自动判断；评测命中时先修文档。
- `sources/guazi/README.md`：只有 fixtures、没有适配器，直接排除。

### 3.2 `docs/tasks/` 是任务档案，不是知识

`docs/tasks/_template/01-brief.md` 这类文件会把需求原句（"XX 记录在哪个表"）带到模板正文上。
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

- ~~**rerank 未实现**~~ → 2026-11-08 已接（默认关），见 2.7；
- BM25 公式没有手算单测；
- ~~加权上限（0.12 / 0.08）按 bigram 的 token 数标定~~ → 加权只剩"模块 +0.06"，见 ARCHITECTURE；
- ~~评估只有 Recall@k~~ → 已补 MRR / nDCG（见 7.6）。

### 7.6 补上 MRR / nDCG 之后：混合的排名反而更差（2026-11-07）

加了 MRR / nDCG 后立刻发现一件反直觉的事：**`hybrid` 的排名质量低于纯 `vector`** ——
Recall 只差一条，但 Top-1 少 5 个百分点。词面那路补了召回能力，同时把噪音带进了前排；
这是 RRF "只合并不裁决"的直接后果，不是实现 bug。

具体数字见 [EVAL.md](EVAL.md) 的「当前基线」（指标表放在那边集中维护，避免每次记数都改动
被索引的文档、进而扰动索引本身）。

两个方向相反的证据：

- `X-Service-Token`：纯向量 top-10 全错，混合能救回第 1 名（**词面救命**）；
- 那条判重键查询：正确答案被 `knowledge-mcp/docs/NOTES.md` 的两节靠 `同源 / 判重 / 什么`
  挤到第 4 名（**自文档污染**，见 2.6 —— 文档越写越"懂行"，越容易和真实问题撞词）。

所以定位要改成：**hybrid 是"能力补齐"，不是"更好的默认"**。要同时拿到召回与排序，
得靠 rerank 或分路加权 —— 两者都还没做。

> **2026-11-08 追记（这条结论已作废）**：分路加权做了（`k=3` + `0.75/0.25`），
> 混合 Top-1 从 65% 回到 90%，与纯语义持平。真正卡住排序的是自文档污染，
> 不是融合策略。见 2.7 与 [EVAL.md](EVAL.md) 的当前基线。

**教训**：只看 Recall@5 的这段时间，我们**误以为** hybrid ≥ vector。补上 MRR/nDCG
才发现相反。**指标选错，结论就会错，而且错得很有信心。**
