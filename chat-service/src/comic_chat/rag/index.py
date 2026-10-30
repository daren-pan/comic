"""RAG 第二、三阶段「切分后的入库」：把 Document 向量化并写进 Chroma。

## 这一步实际发生了什么

```
list[Document]                         (64 条：10 条 FAQ + 54 部作品)
      │
      ├─ embed_documents()  ──→  64 个 1024 维向量（一次批量请求，不是 64 次）
      │
      └─ 写入 Chroma  ──→  <DATA_ROOT>/rag_lab/  目录下
                             ├─ chroma.sqlite3      元数据 + 原文
                             └─ <uuid>/             HNSW 索引二进制
```

⚠️ **「切分」不在这段代码里**：FAQ 的按标题切分发生在 `documents.py`（因为切分策略由
数据形态决定，跟「加载」是同一个决策）。这里只负责向量化和落盘。

## 集合名为什么要带配置指纹

`collection_name` 一旦固定，换了 embedding 模型还往同一个集合里写，会出现两种灾难：
维度不同的直接报错；维度碰巧相同的更糟 —— **查询向量和库里向量不在同一个语义空间，
检索结果完全是噪声，而且不报错**。

所以集合名由 `后端 + 模型 + 维度` 算出一个短哈希。改任何一项配置，自动落到新集合，
旧索引原样保留（想清理就删目录）。这是「换模型必须重建索引」这条规则的工程化兜底：
**与其写文档提醒人别忘，不如让忘了也不出错。**
"""
from __future__ import annotations

from datetime import datetime

from langchain_chroma import Chroma

from . import settings
from .documents import comic_facts, load_all
from .embeddings import get_embeddings

#: 集合名由配置算出（`settings.collection_name()`）—— 本模块只做别名，方便调用处少写一层。
collection_name = settings.collection_name


def get_store() -> Chroma:
    """打开（不存在则创建）向量库句柄。

    `persist_directory` 必须显式给 —— 不给就是纯内存，进程一结束索引消失，
    下次启动 `count()` 归零、检索永远为空（这个坑不报错，只是「查不到东西」）。

    ⚠️ `collection_metadata={"hnsw:space": "cosine"}` 是**必须**的，不是可选优化：

    Chroma 建集合时默认用 **L2 距离**，返回的是**平方** L2 距离（范围 0~4）。
    `langchain-chroma` 再套 `relevance = 1 - distance` 换算（公式是实测反推出来的，
    见 `NOTES.md` §1）—— 于是 distance > 1 时分数就是**负数**（实测 -0.13 / -0.22），
    还会触发 `UserWarning: Relevance scores must be between 0 and 1`。

    显式指定 cosine 后，distance = `1 - cos_sim`（范围 0~2），换算出的分数就等于
    余弦相似度本身（正常文本落在 0~1），可以直接当中文里说的「像不像」用
    （0.9 = 非常像，0.3 = 基本无关）。

    ⚠️ 而且 `collection_metadata` **只在集合首次创建时生效**：集合已经存在时再传，
    会被静默忽略（不报错、也不改）。所以改这一项必须连集合一起重建 ——
    见 `build_index()` 里先 `delete_collection()` 再重开。
    """
    settings.CHROMA_DIR.mkdir(parents=True, exist_ok=True)
    return Chroma(
        collection_name=collection_name(),
        embedding_function=get_embeddings(),
        persist_directory=str(settings.CHROMA_DIR),
        collection_metadata={"hnsw:space": "cosine"},
    )


def build_index() -> dict:
    """全量重建索引（先清空集合，再重新写入）。

    为什么是全量而不是增量：现在 64 条，重建一次不到 2 秒、embedding 花费不到一分钱。
    等作品涨到上千条再考虑「只处理 sync_time 变化的作品」—— 过早优化会让这段代码
    变得难读，而它现在最大的价值是**看清楚完整流程**。

    返回统计信息（CLI 和 HTTP 接口都直接展示它）。
    """
    started = datetime.now()
    # 强制重读 DB：结构化事实的缓存与这份索引同生命周期，重建索引时必须一起刷新，
    # 否则会出现「索引里 54 部、结构化却还是旧的 53 部」这种错位。
    comic_facts(refresh=True)
    docs = load_all()
    if not docs:
        raise RuntimeError("没有可索引的文档：FAQ 为空且漫画表没有数据")

    # ⚠️ 必须先**删掉整个集合**再重开，不能只 `reset_collection()`：
    # 后者只清空向量和文档，集合自身的配置（`hnsw:space` 距离度量）保持原样 ——
    # 而 `collection_metadata` 只在创建时生效，老集合是 l2 度量时，光重置数据
    # 分数仍会是负数（见 `get_store()` 的说明）。删掉重建最省心，代价只是多几百毫秒。
    try:
        get_store().delete_collection()
    except Exception:
        # 集合还不存在（首次建索引）时删会抛错，属正常情况，忽略即可
        pass

    store = get_store()
    store.add_documents(docs)

    elapsed_ms = int((datetime.now() - started).total_seconds() * 1000)
    faq_count = sum(1 for d in docs if d.metadata.get("kind") == "faq")
    return {
        "collection": collection_name(),
        "backend": settings.embedding_backend(),
        "embeddingModel": settings.embedding_model_name(),
        "dim": settings.embedding_dim(),
        "documents": len(docs),
        "faq": faq_count,
        "comics": len(docs) - faq_count,
        "vectors": store._collection.count(),   # noqa: SLF001 —— 取真实写入条数做校验
        "storedAt": str(settings.CHROMA_DIR),
        "elapsedMs": elapsed_ms,
    }
