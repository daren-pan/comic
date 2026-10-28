"""向量化后端：真实语义模型（OpenAI 兼容）或本地哈希占位（无 key 时跑通链路）。

## 三种后端的分工

| 后端 | 触发条件 | 产出的是什么 | 能不能代表真实效果 |
|---|---|---|---|
| `openai` | 配了 `COMIC_EMBED_API_KEY` | 云端语义向量（默认 1024 维） | ✅ 最好 |
| `local` | 装了 `fastembed`（默认会装） | 本地语义向量（bge-small-zh，512 维） | ✅ 够看效果 |
| `hash` | 两者都没有 | **字面重合度**向量 | ❌ 只验证链路 |

`local` 这一档是为学习场景专门留的：`bge-small-zh-v1.5` 离线跑、不要 key、模型 90MB，
CPU 上几十毫秒一条。有了它，「语义检索到底强在哪」这件事**不用花一分钱就能看到**。

`hash` 后端则是最后的兜底：让「加载 → 切分 → 入库 → 检索 → 拼 prompt」这条链路在
**什么都没装**的情况下也能完整跑一遍（第一次搭 RAG 时，最耗时的就是调试这条链路本身，
不该被 key 或模型卡住）。它算相似度的依据是字符 n-gram 的重合度 ——
**看到 `backend: hash` 就该知道检索结果不可信**（实测：问「图片加载不出来」，
正确答案排第 4 位，前面全是毫不相干的漫画简介，纯粹因为长文本字面重合多）。

⚠️ 刻意**不做静默降级**：配了 key 但模型调用失败时直接抛错，不偷偷换成 hash 或 local。
否则你会对着「明明配了 key 效果却像关键词搜索」的结果排查半天。

## 为什么要自己写一个 Embeddings 类

LangChain 的所有检索器只认 `langchain_core.embeddings.Embeddings` 这个协议
（两个方法：`embed_documents` / `embed_query`）。实现它就能无缝插进 Chroma，
不需要适配任何框架内部结构 —— 这也是 LangChain 设计上最实用的地方：**协议窄，实现自由**。
"""
from __future__ import annotations

import hashlib
import math
from functools import lru_cache

from langchain_core.embeddings import Embeddings

from . import settings


class HashNgramEmbeddings(Embeddings):
    """字符 n-gram 哈希伪向量（**不是语义模型**，见模块注释）。

    做法：把文本拆成「单字 + 相邻两字」的 token 序列 → 每个 token 哈希到固定维度的某一格
    → 计数 → L2 归一化。结果是一个稀疏的「字面指纹」：共享 token 越多，余弦相似度越高。

    为什么 bigram 权重高于 unigram：单字重合太容易（「的」「了」到处都是），
    双字组合（「收藏」「密码」）才有区分度。这和 BM25 / TF-IDF 的思路同源，
    只是换成了定长向量以便塞进向量库。
    """

    def __init__(self, dim: int = 1024) -> None:
        self.dim = dim
        self._uni_weight = 0.5
        self._bi_weight = 1.0

    # ---- 内部：文本 → 稀疏计数 ----
    def _tokens(self, text: str) -> list[tuple[str, float]]:
        # 只保留非空白字符并统一小写：`图 裂 了` 与 `图裂了` 应当等价
        s = "".join(ch for ch in text.lower() if not ch.isspace())
        if not s:
            return []
        out: list[tuple[str, float]] = [(ch, self._uni_weight) for ch in s]
        out += [(s[i : i + 2], self._bi_weight) for i in range(len(s) - 1)]
        return out

    def _vec(self, text: str) -> list[float]:
        v = [0.0] * self.dim
        for tok, w in self._tokens(text):
            # md5 前 4 字节 → 稳定（跨进程一致）的桶号。用 Python 内置 hash() 不行：
            # 它对 str 加了随机盐，同一个词在不同进程会落到不同桶，索引和查询就对不上。
            h = int.from_bytes(hashlib.md5(tok.encode("utf-8")).digest()[:4], "big")
            v[h % self.dim] += w
        norm = math.sqrt(sum(x * x for x in v))
        if norm == 0.0:
            return v
        return [x / norm for x in v]

    # ---- LangChain Embeddings 协议 ----
    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        return [self._vec(t) for t in texts]

    def embed_query(self, text: str) -> list[float]:
        return self._vec(text)


class LocalBgeEmbeddings(Embeddings):
    """本地语义模型（`fastembed` + bge-small-zh），**不需要任何 API key**。

    为什么用 `fastembed` 而不是 `sentence-transformers`：后者要装 PyTorch（约 2GB），
    而 fastembed 只依赖 ONNX Runtime —— 后者本项目**已经有了**（chromadb 的传递依赖）。
    净新增依赖不到 10MB，模型首次运行自动下载约 90MB 到用户目录。

    为什么文档和查询用两个方法：bge 系列在训练时给「查询」加过指令前缀（「为这个句子
    生成表示以用于检索相关文章」），`query_embed()` 会自动带上。用同一个方法编码文档和
    查询会损失一点准确率 —— 这个细节很多人不知道，但它是 bge 官方推荐的用法。
    """

    def __init__(self, model_name: str) -> None:
        from fastembed import TextEmbedding

        self._model_name = model_name
        # 首次构造会下载模型（约 90MB）并建 ONNX 会话，通常几秒；之后走本地缓存瞬间完成。
        self._model = TextEmbedding(model_name=model_name)

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        return [vec.tolist() for vec in self._model.embed(list(texts))]

    def embed_query(self, text: str) -> list[float]:
        # query_embed 在部分模型上不可用（没有 query 指令的模型），退回普通 embed
        try:
            return next(iter(self._model.query_embed([text]))).tolist()
        except Exception:
            return next(iter(self._model.embed([text]))).tolist()


@lru_cache(maxsize=1)
def get_embeddings() -> Embeddings:
    """按配置返回向量化后端（进程内只建一次）。

    返回类型是 LangChain 的 `Embeddings` 协议 —— 调用方不需要知道背后是云端模型、本地
    模型还是 hash 占位，`Chroma.from_documents(embedding=...)` 直接吃。
    """
    backend = settings.embedding_backend()

    if backend == "hash":
        return HashNgramEmbeddings(dim=settings.EMBED_DIM)

    if backend == "local":
        return LocalBgeEmbeddings(model_name=settings.LOCAL_MODEL)

    # 延迟到真正要用的地方再 import：没装 langchain-openai 时，其余两个后端仍能工作
    # （实验室的约束之一：核心链路不被打包依赖绑死）。
    from langchain_openai import OpenAIEmbeddings

    return OpenAIEmbeddings(
        model=settings.EMBED_MODEL,
        base_url=settings.EMBED_BASE_URL,
        api_key=settings.EMBED_API_KEY,
        # 通义 text-embedding-v4 支持按需指定输出维度；显式传便于和集合名指纹对应上。
        dimensions=settings.EMBED_DIM,
        # 单次请求条数上限（各家不同，64 对通义是安全的）。批量比逐条快一个数量级。
        chunk_size=64,
    )
