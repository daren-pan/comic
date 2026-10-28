# RAG 实验室 · 踩坑与实测记录

> 按项目约定：`README.md` 讲框架与用法，本文件只记**踩过的坑、实测数字、复盘**。
> 踩到就写，别攒。

## 2026-10-28 首次搭建

### 1. Chroma 默认用 L2 距离，算出来的「相似度」是负数

**现象**：`similarity_search_with_relevance_scores()` 返回 `-0.13`、`-0.22`，
同时 LangChain 抛
`UserWarning: Relevance scores must be between 0 and 1`。

**原因**：两层换算叠出来的。

- Chroma 建集合时默认 `hnsw:space = "l2"`，而且返回的是**平方** L2 距离（范围 0~4）；
- `langchain-chroma` 拿到后按 `relevance = 1 - distance` 换算成相似度。

distance = 1.13 时，`1 - 1.13 = -0.13`。分数越界，阈值判断和展示全乱。

⚠️ **这个公式最初写成了 `1 - distance/2`，是错的** —— 2026-10-28 实测反推才定案：

```
Chroma 原始 distances : [0.4776, 0.5688, 0.6024]
LangChain relevance   : [0.5224, 0.4312, 0.3976]
若 score = 1 - d      → [0.5224, 0.4312, 0.3976]   ← 完全吻合
若 score = 1 - d/2    → [0.7612, 0.7156, 0.6988]   ← 对不上
```

教训：**框架内部的换算逻辑不要凭印象写进注释**，跑一次 `_collection.query(include=["distances"])`
和 `similarity_search_with_relevance_scores()` 对一下就有答案。

**修法**：建集合时显式指定 `collection_metadata={"hnsw:space": "cosine"}`。
cosine 距离 = `1 - cos_sim`（范围 0~2），`1 - distance` 得到的正好是余弦相似度本身，
正常文本落在 0~1。
代价是所有向量要归一化（`text-embedding-v4` 和 bge 默认就是归一化的，无额外工作）。

**衍生坑（更隐蔽）**：`collection_metadata` **只在集合首次创建时生效**。集合已存在时再传
这个参数会被**静默忽略** —— 不报错、不警告、分数照旧是负的。所以改度量方式必须
`delete_collection()` 后重建，光 `reset_collection()`（只清数据）没用。

### 2. `strip_headers=False` 让正文和标题重复一遍

**现象**：检索预览里是 `## 忘记密码怎么办  忘记密码怎么办…` 这样的重复。

**原因**：`MarkdownHeaderTextSplitter` 把标题同时放进了 `metadata` 和（`strip_headers=False` 时）
`page_content`。而拼 prompt 时我们本来就用 `metadata.title` 打了个 `[FAQ] 标题` 标签。

**修法**：`strip_headers=True`（也就是默认值），标题只留 metadata。省 token，预览也干净。

### 3. 站内标题混着繁体，简体搜不到

**现象**：库里 54 部作品有相当一部分是繁体标题（《創世的大河》《邂逅雨中貉》），
而用户提问只会用简体。

**修法**：拼 `page_content` 时用 `zhconv.convert(text, "zh-cn")` 统一转简体
（`zhconv` 本来就在 comic-core 的依赖里，采集端跨源去重也在用）。

⚠️ **`metadata.title` 保留原文** —— 它要用于界面展示和跳转，不该因为我们做检索优化
就改变用户看到的书名。

### 4. hash 占位后端（无 key、无本地模型时）会让长文本占优

**实测**：问「图片加载不出来怎么办」，正确答案（FAQ「图片加载不出来怎么办」）排**第 4**，
前三条是两个毫不相干的漫画简介和一条收藏 FAQ。

**原因**：hash 后端算的是字符 n-gram 重合度，**文本越长、token 越多、哈希碰撞机会越多**，
相似度天然偏高。这是词袋类方法的固有缺陷，不是 bug。

**结论**：`hash` 只用来验证「链路通不通」，**不能用来判断效果**。看效果必须切 `local`
（本地 bge）或 `openai`（云端）。CLI 和接口响应里都带 `backend` 字段和 `warning`，
就是为了防止有人对着 hash 的结果下结论。

### 5. DeepSeek 的两个事实（2026-10 核对）

| 事实 | 影响 |
|---|---|
| `deepseek-chat` / `deepseek-reasoner` 已于 **2026-07-24 退役** | 现名 `deepseek-flash` / `deepseek-v4-pro`。用旧名不会报错，但会被路由到已退役模型，属于随时可能失效的写法 |
| **不提供 embedding 接口**（`/embeddings` 不存在，调用 400） | 向量化必须另找一家：云端用通义 `text-embedding-v4`（OpenAI 兼容），离线用 bge |

### 6. fastembed 直连 HuggingFace 下载模型失败（国内网络）

**现象**：

```
ValueError: Could not load model BAAI/bge-small-zh-v1.5 from any source.
```

**修法**：设镜像端点后再跑（首次下载约 90MB，之后走本地缓存）：

```bash
HF_ENDPOINT=https://hf-mirror.com python -c "from fastembed import TextEmbedding; TextEmbedding('BAAI/bge-small-zh-v1.5')"
```

Windows CMD 用 `set HF_ENDPOINT=https://hf-mirror.com`，PowerShell 用 `$env:HF_ENDPOINT="..."`。

### 7. 环境事实

- 项目 venv 是 **Python 3.13.17**，langchain / chromadb / fastembed 全部有 cp313 预编译 wheel，
  **不需要编译工具链**（`pip install langchain langchain-openai langchain-chroma chromadb` 实测约 2 分钟）。
- 这一套拉进来 **80+ 个传递依赖**，包括 `kubernetes`、`grpcio`、`onnxruntime`、
  `opentelemetry-sdk`、`tokenizers`、`aiohttp`。这就是「生产镜像不装它」的直接原因。
- MySQL 实测 **8.0.46，没有 `VECTOR` 类型**（9.0 才引入），所以向量不能存 MySQL，
  必须独立向量库。
