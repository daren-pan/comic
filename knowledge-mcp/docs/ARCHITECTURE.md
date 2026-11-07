# 架构与设计

> 这份文档只讲**结构、契约和取舍**。要跑命令看 [OPERATIONS.md](OPERATIONS.md)，
> 要查参数看 [CONFIG.md](CONFIG.md)，踩坑记录看 [NOTES.md](NOTES.md)。

## 一、数据流

```
              ┌──────────── 建索引（离线，改文档才跑）────────────┐
仓库文档 ──┐  │                                                  │
schema/API ─┼─→ corpus 加载 ─→ 按标题树切 chunk ─→ 向量化 ─→ Chroma │
用户资料 ──┘  │  (external)      (双文本)                      │   │
              └──────────────────────────────────────────────────┘
                                    │
              ┌──────────── 检索（在线，每次查询）───────────────┐
查询 ─────────┴─→ ┌ 向量：余弦 + 标题/模块/正文加权 + 阈值        │
                    └ BM25：词面命中（倒排索引，内存）           │
                       ↓                                        │
                    RRF 按名次融合 ─→ 按小节去重 ─→ top_k 命中      │
                       ↓                                        │
                    read_knowledge 按 doc_id 回读小节全文          │
              └──────────────────────────────────────────────────┘
```

两段是**解耦**的：检索时 BM25 索引从 Chroma 现读文档现场构建（几十毫秒），
不需要第二份持久化索引；向量集合则要显式重建。

## 二、语料来源

**纳入：**

- 根 `README.md`、`AGENTS.md`
- `docs/**/*.md`（`docs/architecture.md` 标 `historical`，默认不检索）
- 各模块 `README.md` / `NOTES.md`
- `crawler-service/src/comic_crawler/sources/*/README.md`
- `comic-core/sql/mysql_schema.sql`：一张表一个 chunk
- `api-service/openapi.json`：一个端点一个 chunk
- 外部文档目录（默认 `crawler-service/data/kb_docs/`）：`.md` / `.docx` / `.xlsx`

**排除：**

- `.git/`、`node_modules/`、`.venv/`、`.python/`
- `logs/`、`backup/`、`build/`、`dist/`
- `crawler-service/data/`（图库 / 索引 / 模型缓存）
- `.workbuddy/`、`.agent-shared/`
- 所有 `.env` / 密钥文件
- `docs/tasks/`（需求档案，不是稳定知识）
- `sources/guazi/README.md`（只有 fixtures、没有适配器）

**为什么不索引代码**：代码的强项是精确符号匹配（`ripgrep` / AST），
语义检索适合"已经用自然语言解释过"的内容。混进来只会稀释文档的语义空间。

## 三、切分

### 为什么按标题树切，而不是按字符数

一个 `chunk_size=500` 走天下会把 FAQ 从小节中间截断 —— 检索到半截语义，模型看不懂。
标题层级是**作者已经标好的语义边界**，优先用它；只有单节太长时才退化到按段落/句号切。

### 硬约束：embedding 模型的 512 token

`bge-small-zh-v1.5` 的 `max_position_embeddings = 512`，中文 1 字约 1 token。
**超长的后半段会被 tokenizer 静默截断**（不报错），表现为"文档里明明写了，检索就是找不到"。

| 参数 | 值 | 说明 |
|---|---|---|
| 目标 chunk | 300–400 中文字符 | 留足余量 |
| 硬上限 | 500 字符 | |
| token 硬上限 | 480 | 给标题与特殊 token 留余量 |
| 最小 chunk | 120 字符 | 更小的与相邻小节合并 |
| 长段落重叠 | 50 字符 | 仅在被强制切开长文本时 |

### 切分规则

1. 按 H1/H2/H3 标题树切，每个 chunk 带 `heading_path`（如 `部署 / 端口与反代`）；
2. **代码块、表格是原子块**，不从中间切；表格超长时按行切并**重复表头**；
3. 单块代码超过 500 字时整块保留（半截代码比长代码更糟），接受 token 超限；
4. 切完再用 tokenizer 复核 token 数，超限的继续拆；
5. 每个 chunk 记录 `parent_start` / `parent_end`，供回读整节时定位。

### 双文本契约：检索文本 ≠ 展示文本

每条 `Document` 存两份文字，这是本模块最重要的一个设计：

| 字段 | 内容 | 用途 |
|---|---|---|
| `page_content` | FAQ：标题 + 正文首句<br>漫画：书名 + 作者 + 标签 + 简介 | **只拿去算向量与 BM25** |
| `metadata["display"]` | 完整原文 | **只拿去拼上下文 / 回读** |

**为什么不合成一份**：向量是整段文字的平均值。用户问句往往只有 4~6 字，
拿去跟 150 字的完整正文比，相似度会被稀释到阈值以下（实测：合成一份 0.489，
分离后 0.56）。**模型读到的内容不变，变的只是"拿去比对的那段文字"。**

> 改 `page_content` 的拼法必须把 `CHUNKER_VERSION` 加一，否则会继续用旧向量 ——
> 症状是"代码明明改了、效果一点没变"，而且不报错。

## 四、分词（词项层）

两处依赖"把一句话切成词"：**标题/正文加权**（`retriever` 的 boost）和 **BM25 召回**。
两处必须同一套切法，所以统一收在 `tokenizer.py`，可切三个后端：

| 后端 | 切法 | 特点 |
|---|---|---|
| `mixed`（默认） | 标识符整体保留 + 部件展开，中文段交 jieba | 中英兼顾 |
| `jieba` | 词典 + DAG + 最大概率路径 + HMM 未登录词 | 中文好，英文标识符会被拆碎 |
| `bigram` | 英文/数字整词 + 中文两字滑窗 | 零依赖，中文有跨词碎片噪音 |

**为什么默认 `mixed`**：中文两字词在 bigram 与词典切分下**完全等价**，差异只出现在
三字以上词和虚词碎片上；而英文/数字标识符（`require_admin`、`X-Service-Token`）
恰好是 bigram 保整体、jieba 拆碎。分流后两边优点都拿到：

```
require_admin 是哪个装饰器 → require_admin, require, admin, 哪个, 装饰
图床地址是什么            → 图床, 地址, 什么        （不会产生 是什 这种假词）
```

**用户词典**（`src/comic_rag_mcp/terms.txt`）：jieba 默认词典不认识
「判重 / 图床 / 管理台 / 按需导入」这类项目术语，不配词典时它们会被切碎，
**上 jieba 反而比 bigram 更差**。新增模块术语要一并补进来。

> ⚠️ **换分词器 = 换打分刻度**：BM25 的分数是逐词求和，分词一变，
> 加数个数、词频口径、文档长度基准、IDF 分布全变。
> 换后端后必须重跑评估集并重标权重，与换 embedding 模型是同一类问题。

## 五、检索：双路 + RRF

```
查询
 ├─ 向量路：Chroma 余弦 → 标题/模块/正文加权 → min_score 过滤 → 排名次
 └─ BM25 路：倒排索引打分 → 排名次
      ↓
   RRF = Σ 1/(k + 名次)   k=60
      ↓
   按 (path, heading_path) 去重（同一小节只留最高分）
      ↓
   top_k
```

### 为什么要两条路

不是精度高低，是**能力类型不同**：

- 向量回答「哪一条最像」，擅长口语、错字；
- 词面回答「哪几条含这些词」，擅长型号、报错码、函数名、专有名词。

实测：查 `X-Service-Token` 时向量 top-10 一条都不对（它把"鉴权相关"的 openapi 排前面），
BM25 第 1 名即正确。反过来查「某术语 + 是什么」这类疑问句时，BM25 会把 NOTES 的
「条目模板」章节捞上来（它们含"是什么"），向量那路没这个毛病。

### 为什么按名次融合，不按分数相加

向量分是 0~1 余弦，BM25 是**无上界实数**（实测 0.4~20），两者不可比。
直接相加，量级大的那一路永远赢，等于另一路白做。RRF 只看名次，天然免疫量纲问题。

### 三个必须知道的语义

1. **`score` 的含义随模式变化**：`vector` 模式是余弦（0~1），`hybrid` 模式是 RRF 分
   （`1/(60+名次)` 量级，约 0.016）。要判断"像不像"请读 `vector_score`。
2. **`min_score` 只作用在向量那一路**。融合后分数量级完全不同，拿 0.45 卡会一条不剩。
3. **RRF 只合并、不裁决**。两路各自排名第一的两条，融合分**完全相同**，
   排序退化成按 `doc_id` 字典序 —— 这是设计边界，该由二次重排（rerank）解决，
   **不要靠调 `RRF_K` 去凑**（它只改变量级）。

## 六、索引与集合指纹

- 目录：`crawler-service/data/project_rag`（可用 `COMIC_RAG_INDEX_DIR` 覆盖）
- 集合：`project_kb_<backend:model:dim:chunkN 的短哈希>`
- 距离度量：**必须 cosine**。Chroma 默认 L2，`langchain-chroma` 用 `1 - distance` 换算，
  于是 distance>1 时分数变负数（实测 -0.13 / -0.22）；且 `collection_metadata`
  **只在集合首次创建时生效**，所以重建时必须先 `delete_collection()` 再重开。

**集合名带配置指纹**，是为了把"换模型必须重建索引"这条规则变成工程兜底：
换个 embedding 模型还往同一个集合里写，维度不同的直接报错，**维度碰巧相同的更糟 ——
向量不在同一个语义空间，检索结果是噪声，而且不报错**。带指纹后改配置自动落到新集合，
旧索引保留。

- `manifest.json`：每个文件的 sha1 / 大小 / chunk 数、embedding 参数、切分版本、构建时间
- **过期检测**：对比当前文件与 manifest，输出 `changed / new / missing` 三个列表

## 七、回读契约：`read_mode`

| 值 | 适用 | 行为 |
|---|---|---|
| `lines` | Markdown / SQL（文件真实存在且是纯文本） | 按 `parent_start/end` 回读**原文件行号区间**，拿到整节 |
| `chunk` | OpenAPI / Word / Excel（没有稳定行号） | 只返回命中的那条 chunk 正文 |

Word / Excel **不做 section 级回读**是有意接受的限制：原始文件是二进制，
Word 转出的中间 Markdown 在磁盘上并不存在，没有行号可回。

命中结果按 `(path, heading_path)` 去重：一个长小节会切成多个 chunk，
`read` 反正会回读整节，重复 chunk 只会挤占 `top_k`。

## 八、message 子索引

message 表**不直连数据库**，而是由 api 的只读接口暴露：

```
GET /api/internal/knowledge/messages?cursor=&limit=
X-Service-Token: <HMAC>
```

- 按 `id` 升序返回**全量**行（不做收件范围过滤）；
- 消息表是**追加式**（没有 `updated_at`），所以增量游标就是 `id > last_id`；
- 因为含定向/管理员消息，**只认服务令牌、不认用户 JWT**；
- 集合 `project_kb_message_*` **与文档集合分开**：消息增量刷新不该触发文档全量重建。

## 九、进程与权限边界

| 关注点 | 做法 |
|---|---|
| 对外形态 | MCP stdio，不监听端口；只有本机 Agent 能拉起 |
| 写能力 | 无。只读 Chroma、只 GET 内部接口 |
| 生成 | 不调用对话模型（那是 chat-service 的职责） |
| 失败语义 | 索引缺失/为空/版本不匹配时抛 `ToolError`，**不返回空 hits 假装"没有资料"** |
| 依赖边界 | 复用 chat-service 的 embedding 与 Chroma 技术栈，但与它的索引互不干扰 |
