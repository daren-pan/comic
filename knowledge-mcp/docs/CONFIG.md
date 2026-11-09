# 配置参考

> 只列**可调项与其影响**。怎么用见 [OPERATIONS.md](OPERATIONS.md)，为什么这么设计见
> [ARCHITECTURE.md](ARCHITECTURE.md)。默认值以 `src/comic_rag_mcp/config.py` 为准。

所有变量都是**可选**的，不设就用默认值。路径类的相对路径一律按**仓库根**解析。

## 一、路径

| 变量 | 默认 | 作用 | 注意 |
|---|---|---|---|
| `COMIC_RAG_ROOT` | 由 `config.py` 位置上溯三级 | 仓库根 | 容器/打包态必须显式指定 |
| `COMIC_RAG_INDEX_DIR` | `<root>/crawler-service/data/project_rag` | Chroma 落盘目录 | 必须**绝对路径**，相对路径会被忽略并回落默认；指错时"索引写了但下次启动归零"且不报错 |
| `COMIC_KB_DOCS_DIR` | `<root>/crawler-service/data/kb_docs` | 外部文档（Word/Excel/Markdown）目录 | 可以指到仓库外的任意目录 |

## 二、切分

| 变量 | 默认 | 作用 |
|---|---|---|
| `COMIC_RAG_TARGET_CHARS` | 400 | 目标 chunk 字符数 |
| `COMIC_RAG_MAX_CHARS` | 500 | 硬上限（超出强制切） |
| `COMIC_RAG_MIN_CHARS` | 120 | 最小 chunk；更小的与相邻小节合并 |
| `COMIC_RAG_MAX_TOKENS` | 480 | token 硬上限（bge 512，留余量） |
| `COMIC_RAG_OVERLAP_CHARS` | 50 | 被迫切开长段落时的重叠字符 |

> 改这些值等于改**切分契约**：`CHUNKER_VERSION` 要加一（它是代码常量，不是环境变量），
> 然后重建索引。

## 三、检索 · 向量路

| 变量 | 默认 | 作用 | 注意 |
|---|---|---|---|
| `COMIC_RAG_TOP_K` | 5 | 最终返回几条 | 3 条常不够，8 条以上开始稀释 |
| `COMIC_RAG_MIN_SCORE` | 0.45 | 余弦阈值 | **只作用在向量那一路**；混合模式下融合分是 `1/(60+名次)`，拿它卡会一条不剩 |
| `COMIC_RAG_READ_MAX_CHARS` | 6000 | `read_knowledge` 单次返回上限 | 超出截断并标记 `truncated` |

## 四、检索 · 词面路（BM25）与融合

| 变量 | 默认 | 作用 | 注意 |
|---|---|---|---|
| `COMIC_KB_HYBRID` | `1` | 双路总开关 | 设 `0` 完全回到纯向量（回退用） |
| `COMIC_KB_LEXICAL_TOP_K` | 20 | 词面路候选数 | 只用于融合，不是最终返回数 |
| `COMIC_KB_LEXICAL_K1` | 1.8 | 词频饱和系数 | 越大，"出现次数多"越占便宜；1.5→1.8 使字面 Top-1 50%→60% |
| `COMIC_KB_LEXICAL_B` | 0.9 | 长度归一强度 | 0 = 不惩罚长文，1 = 完全按长度摊平；0.75→0.9 是同一轮调参 |
| `COMIC_RAG_BOOST` | `module` | 语义分加成策略 | `module`（默认，+0.06 命中模块）/ `none` / `heading` / `body` / `all`；实测 `module` 最好，见 [ARCHITECTURE.md](ARCHITECTURE.md) |
| `COMIC_RAG_RERANK` | 空（关闭） | 重排总开关 | 设 `1` 打开。**默认关**：当时基线（k=60 等权、混合 Top-1 65%）下测到 70%，但每次查询 50ms→7s，且语义掉到 70%；现有基线已 90%，**未复测**，见 [NOTES.md](NOTES.md) 2.7 |
| `COMIC_RAG_RERANK_MODEL` | `crawler-service/data/models/bge-reranker-v2-m3` | 重排模型目录 | 2.1 GB，`BAAI/bge-reranker-v2-m3`（多语言，中文可用） |
| `COMIC_RAG_RERANK_CANDIDATES` | 10 | 送进重排的候选数 | 每多一条约 +0.7 秒（CPU） |
| `COMIC_RAG_RERANK_MAX_LENGTH` | 256 | 重排截断长度 | 越大越慢 |
| `COMIC_KB_RRF_K` | 3 | RRF 平滑常数 | **会改变排序**：k 越大，"两路都出现"越吃香；k=60 会让"两路靠后"压过"单路第一" |
| `COMIC_KB_RRF_WEIGHTS` | `1,1` | 两路权重（语义, 字面） | 默认**等权**。曾用 `0.75,0.25`：文档原话式题集上 Top-1 更高，但会把"字面对、混合错"的三条（专名类与短问句各一条）压掉 |
| `COMIC_RAG_AUTO_ROUTE` | `1` | 按查询类型分流 | 口语型走「改写+合并+重排」（10~45 秒），其余 40ms；**只对混合检索生效** |
| `COMIC_RAG_FUSION` | `rrf` | 融合方式 | `rrf`=按名次加权求和；`interleave`=两路轮流取（实测 Top-1 60%→66.7%、Recall 不变），默认不改 |
| `COMIC_RAG_SYNONYMS` | `1` | 同义词扩展 | 查询里的用户说法按 `synonyms.json` 扩成语料用词，**只加进字面路** |

## 五、分词

| 变量 | 默认 | 作用 |
|---|---|---|
| `COMIC_KB_TOKENIZER` | `auto` | `auto` = 装了 jieba 走 `mixed`，否则 `bigram`；也可强制 `mixed` / `jieba` / `bigram` |

- 强制 `mixed` / `jieba` 但没装 jieba 时**直接报错**（不静默降级）；
- 用户词典是文件不是环境变量：`src/comic_rag_mcp/terms.txt`（一行一词，可带词频/词性，`#` 注释）；
- **换后端 = 换打分刻度**：必须重跑评估集（见 [EVAL.md](EVAL.md)），且 `LEXICAL_K1/B`
  与标题加权上限都要重新标定。

## 六、外部文档（Word / Excel）

| 变量 | 默认 | 作用 |
|---|---|---|
| `COMIC_KB_XLSX_MAX_ROWS` | 2000 | 单表最多读多少行（一行一个 chunk，防止几万行撑爆索引） |
| `COMIC_KB_XLSX_CELL_CHARS` | 300 | 单元格最大字符数 |
| `COMIC_KB_XLSX_MAX_COLS` | 30 | 最多读多少列（宽表对检索没有意义） |
| `COMIC_KB_DOCX_CELL_CHARS` | 200 | Word 表格单元格最大字符数 |

## 七、message 子索引

| 变量 | 默认 | 作用 |
|---|---|---|
| `COMIC_KNOWLEDGE_MESSAGE_URL` | `http://127.0.0.1:8000/api/internal/knowledge/messages` | 拉取消息的内部接口 |
| `COMIC_KNOWLEDGE_MESSAGE_TIMEOUT` | 10 | 拉取超时（秒） |
| `COMIC_RAG_MESSAGE_MAX_CHARS` | 1200 | 单条消息进索引的最大字符数 |
| `COMIC_RAG_MESSAGE_MIN_SCORE` | 0.30 | 消息检索阈值（消息短、同义表达多，比文档阈值低） |

> 内部接口要服务令牌：**复用 `COMIC_JWT_SECRET`** 做 HMAC。本地默认值
> （`comic-demo-secret-change-me`）是公开的，**生产必须显式设成强随机值，且 api 与
> indexer 两侧一致**。

## 八、由 chat-service 提供（共用）

这些不在本模块的 `config.py` 里，但直接影响它 —— 变更是同一个 venv 里共享的：

| 变量 | 作用 |
|---|---|
| `COMIC_EMBED_API_KEY` / `COMIC_EMBED_MODEL` / `COMIC_EMBED_DIM` | 用云端 embedding 时的参数（不设则走本地 bge） |
| `FASTEMBED_CACHE_PATH` | 本地模型缓存目录（`dev.sh` / `run_mcp.py` 会自动指到项目内） |
| `HF_ENDPOINT` | HuggingFace 镜像，国内建索引必备 |
| `TMP` / `TEMP` / `TMPDIR` | Chroma 的 Rust SQLite 与 fastembed 会直接读它们，**三个都要设** |

## 九、调参纪律

1. **一次只改一个变量**，否则说不清是谁的效果；
2. 改完**先跑评估集**（`EVAL.md`），再决定留不留；
3. **换 embedding 模型** → 必须重建索引（集合名会自动变，旧集合保留）；
4. **换分词器** → 不用重建向量索引，但必须重标阈值与加权；
5. 任何"调好了"的结论都要写进 [NOTES.md](NOTES.md)，否则下次没人知道为什么是这个值。
