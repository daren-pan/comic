"""comic-chat 的 HTTP 服务（**内网，无鉴权**）。

## 谁能访问

只有同一 compose 网络里的 `comic-api` 能访问（`http://comic-chat:8001`）。
本服务**不映射宿主端口**，也不做任何身份校验 —— 鉴权和限流在 api 那层
（`api-service/routers/chat.py`）。这是刻意的分工：

- 鉴权要读 `user` 表、要复用 `core/security.py`（api-service 的模块），搬不过来这里；
- 本服务只认「一个问题换一个答案」，不需要知道是谁在问。

⚠️ 因此**绝不能**给它加 `ports:` 映射到公网 —— 那等于把模型额度白送出去。

## 端点

| 端点 | 用途 |
|---|---|
| `GET /health` | 存活 + 当前向量后端/集合/向量数（api 的 503 提示也会打这里） |
| `POST /ask` | 客服问答（api 转发） |
| `POST /lab/index` | 重建索引 |
| `POST /lab/search` | 只检索、带分数（排查用） |
| `GET /lab/status` | 配置自检（**不返回任何密钥内容**） |
"""
from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException

from .rag import chain, settings
from .rag.index import build_index, get_store
from .schemas import AskBody, LabAskBody, SearchBody

_log = logging.getLogger("comic.chat")


def _ensure_index() -> None:
    """启动时若索引为空就建一次（新部署 / 清了数据目录后的第一次启动）。

    **失败不拦启动**：MySQL 没就绪、模型下载不到时，让它带着空索引起来 ——
    `/health` 会把 `vectors` 报成 0，比"容器起不来、只能看日志"好排查得多
    （与 api 启动时 `reap_stale` 的处理同一原则）。
    """
    try:
        count = get_store()._collection.count()   # noqa: SLF001 —— 只读计数
        if count > 0:
            _log.info("索引已存在：%d 条向量（%s）", count, settings.collection_name())
            return
        _log.info("索引为空，开始首次构建…")
        stats = build_index()
        _log.info(
            "首次建索引完成：%d 个文档 → %d 条向量，耗时 %dms",
            stats["documents"], stats["vectors"], stats["elapsedMs"],
        )
    except Exception as exc:   # noqa: BLE001 —— 启动期任何异常都不该让进程退出
        _log.warning("索引检查/构建失败（服务照常启动，但问答会查不到资料）：%s", exc)


@asynccontextmanager
async def lifespan(_app: FastAPI):
    _ensure_index()
    yield


app = FastAPI(title="Comic Chat", version="1.0.0", lifespan=lifespan)


@app.get("/health")
def health() -> dict:
    """存活探针 + 索引状态。api 那边连不上或返回异常时会指向这里排查。"""
    vectors = 0
    collection = ""
    error = ""
    try:
        collection = settings.collection_name()
        vectors = get_store()._collection.count()   # noqa: SLF001
    except Exception as exc:   # noqa: BLE001
        error = str(exc)

    return {
        "ok": not error,
        "backend": settings.embedding_backend(),
        "embeddingModel": settings.embedding_model_name(),
        "dim": settings.embedding_dim(),
        "collection": collection,
        "vectors": vectors,
        "llmReady": settings.llm_ready(),
        "indexDir": str(settings.CHROMA_DIR),
        "error": error,
    }


@app.post("/ask")
def ask(body: AskBody) -> dict:
    """客服问答。`with_context=False` —— 调试用的完整上下文只在 `/lab` 返回。

    `history` 由前端带上来（本服务不存会话）：查不到资料且有上文时，会先把追问改写成
    独立问题再重查一次（逻辑见 `rag/chain.py` 的 `ask()`）。
    """
    try:
        result = chain.ask(
            body.question,
            with_context=False,
            history=[t.model_dump() for t in body.history],
        )
    except RuntimeError as exc:
        # 没配 key / 调用失败：503 + 中文原因，api 会原样转给前端
        raise HTTPException(status_code=503, detail=str(exc)) from exc

    _log.info(
        "问答：len=%d 历史=%d 改写=%s 命中=%d",
        len(body.question), len(body.history), bool(result.get("rewritten")),
        len(result["hits"]),
    )
    return {
        "answer": result["answer"],
        # 只给标题：正文和分数属于调试信息
        "hits": [{"title": h["title"], "kind": h["kind"]} for h in result["hits"]],
        # 改写结果回传：前端可以据此显示「理解为：xxx」，也是排查多轮是否生效的唯一线索
        "rewritten": result.get("rewritten"),
        "model": result["model"],
        "elapsedMs": result["elapsedMs"],
    }


@app.post("/lab/index")
def lab_index() -> dict:
    """全量重建索引（改过 faq.md 或采集了新作品之后跑）。"""
    return build_index()


@app.post("/lab/search")
def lab_search(body: SearchBody) -> dict:
    """只检索、不调生成模型 —— 调试 RAG 时**先用这个**。"""
    min_score = body.minScore if body.minScore is not None else -1.0
    return chain.search(body.question, k=body.topK, kind=body.kind, min_score=min_score)


@app.post("/lab/ask")
def lab_ask(body: LabAskBody) -> dict:
    """完整问答，**带调试信息**（`context` = 实际发给模型的资料原文）。

    和 `/ask` 的区别只有两点：能调 `topK` / `kind`、返回 `context`。
    拆成两个端点而不是加个开关，是因为前者给前台（不该看内部 prompt），
    后者给管理员排查 —— 权限边界不同，混在一起容易漏判。
    """
    try:
        return chain.ask(
            body.question, k=body.topK, kind=body.kind, with_context=body.withContext
        )
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc


@app.get("/lab/status")
def lab_status() -> dict:
    """配置自检。`describe()` 只回布尔值，不回显任何 key 片段。"""
    return settings.describe()
