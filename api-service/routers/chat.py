"""RAG 实验室 HTTP 接口（`/api/chat/lab/*`）—— **学习用沙盒，不是生产客服**。

## 谁能调

`require_admin`（超管或普通管理员）。之所以不给匿名用：这几个接口会真的花钱（调 embedding /
对话模型），挂在公网就是白嫖入口。

## 开关

默认**开启**（本地学习场景开箱即用）；`COMIC_CHAT_LAB=0` 显式关闭时，`main.py` 不挂载本
路由 —— 请求会直接 404，而不是 403。生产部署应当设成 0，并**不安装**
`requirements-lab.txt`（那样即使误开也会在 import 处报 503，不会真的跑起来）。

## 为什么所有业务 import 都写在函数里

`services.chat.lab` 会连带加载 langchain / chromadb（80 多个依赖）。这些依赖**不进生产镜像**，
所以本模块在顶层只 import fastapi 与项目内的轻量模块 —— 没装依赖时 `main.py` 照常启动，
只有真的请求这几个接口才会拿到 503 + 一句「请先装 requirements-lab.txt」。
"""
from __future__ import annotations

import logging
import os
import time

from fastapi import APIRouter, Depends, HTTPException, Request

from core.responses import ok
from core.security import require_admin
from schemas import ChatAskBody, ChatLabBody

router = APIRouter(tags=["chat-lab"])
_log = logging.getLogger("comic.chat.lab")

#: 默认开。要关就 `COMIC_CHAT_LAB=0`（生产部署建议关掉）。
_DISABLED_VALUES = {"0", "false", "no", "off"}

# ---- 公开客服接口的限流（内存滑动窗口，进程内）----
# 为什么放在进程内而不是库表：现在只有一个 api 进程，重启清零完全可接受；
# 换成 Redis/表会多一个部署依赖，等真有多副本再说。
# ⚠️ 多副本部署时这条限流会失效（每个进程各算一份），届时必须换共享存储。
_RATE: dict[str, list[float]] = {}
_RATE_WINDOW = 3600          # 窗口：1 小时
_RATE_LIMIT_USER = 60        # 登录用户：60 条/小时
_RATE_LIMIT_ANON = 15        # 未登录：15 条/小时/IP


def _rate_allow(key: str, limit: int) -> bool:
    """滑动窗口限流：窗口内次数没超就记账并放行。"""
    now = time.time()
    stamps = [t for t in _RATE.get(key, []) if now - t < _RATE_WINDOW]
    if len(stamps) >= limit:
        _RATE[key] = stamps
        return False
    stamps.append(now)
    _RATE[key] = stamps

    # 防止字典随访问者无限膨胀：超过 5000 个 key 时清掉整个窗口内没动静的
    if len(_RATE) > 5000:
        for k in [k for k, v in _RATE.items() if not v or now - v[-1] > _RATE_WINDOW]:
            del _RATE[k]
    return True


def _client_key(request: Request, user: dict | None) -> str:
    """限流用的身份键：登录用户按账号，匿名按真实 IP。

    ⚠️ 必须优先读 `X-Forwarded-For`：容器里请求经过 nginx 反代，`request.client.host`
    拿到的是**nginx 的地址**（所有用户同一个）—— 直接用它，全站会共用一个额度，
    一个人问 15 次所有人就被挡住。
    """
    if user:
        return f"u:{user.get('id')}"
    xff = request.headers.get("x-forwarded-for", "")
    ip = xff.split(",")[0].strip() if xff else ""
    if not ip and request.client:
        ip = request.client.host
    return f"ip:{ip or 'unknown'}"

_MISSING_DEPS_HINT = (
    "RAG 实验室依赖未安装：请在项目根目录执行 "
    "`crawler-service/.venv/Scripts/python.exe -m pip install -r api-service/requirements-lab.txt`"
)


def enabled() -> bool:
    """路由是否挂载（`main.py` 在装配时问一次）。"""
    return os.environ.get("COMIC_CHAT_LAB", "1").strip().lower() not in _DISABLED_VALUES


def _lab_chain():
    """取 `lab.chain` 模块；依赖没装时转成 503 而不是 500。"""
    try:
        from services.chat.lab import chain
    except ImportError as exc:  # pragma: no cover - 只在未装依赖的环境触发
        _log.warning("RAG 实验室不可用：%s", exc)
        raise HTTPException(status_code=503, detail=_MISSING_DEPS_HINT) from exc
    return chain


def _lab_index():
    try:
        from services.chat.lab import index
    except ImportError as exc:  # pragma: no cover
        raise HTTPException(status_code=503, detail=_MISSING_DEPS_HINT) from exc
    return index


@router.get("/api/chat/lab/status")
def lab_status(_admin: dict = Depends(require_admin)):
    """配置自检：当前用哪个向量后端、有没有 key、索引在哪。**不返回任何密钥内容**。"""
    from services.chat.lab import settings

    return ok(settings.describe())


@router.post("/api/chat/lab/index")
def lab_index(_admin: dict = Depends(require_admin)):
    """全量重建索引（改过 faq.md 或采集了新作品之后要跑一次）。

    同步阻塞几百毫秒到几秒（本地模型）/ 几秒到几十秒（云端模型，视条数而定）。
    数据量还小，不做成后台任务 —— 做成任务反而看不出「重建到底多慢」。
    """
    stats = _lab_index().build_index()
    _log.info("RAG 索引重建完成：%s 条向量", stats.get("vectors"))
    return ok(stats)


@router.post("/api/chat/lab/search")
def lab_search(body: ChatLabBody, _admin: dict = Depends(require_admin)):
    """只检索、不调生成模型 —— 调试 RAG 时**先用这个**。"""
    chain = _lab_chain()
    # minScore 不传时用后端默认阈值；传 0 表示不过滤（想看全部候选）
    min_score = body.minScore if body.minScore is not None else -1.0
    return ok(chain.search(body.question, k=body.topK, kind=body.kind, min_score=min_score))


@router.post("/api/chat/lab/ask")
def lab_ask(body: ChatLabBody, _admin: dict = Depends(require_admin)):
    """完整问答。没有配置对话模型 key 时返回 503（错误信息里说明该配哪个变量）。"""
    chain = _lab_chain()
    try:
        result = chain.ask(
            body.question, k=body.topK, kind=body.kind, with_context=body.withContext
        )
    except RuntimeError as exc:
        # 「没配 key」是配置问题不是程序错误，用 503 而不是 500
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    return ok(result)


@router.post("/api/chat/ask")
def chat_ask(
    body: ChatAskBody,
    request: Request,
    user: dict = Depends(require_admin),
):
    """**客服提问**（网站右侧悬浮球调的接口）。

    ⚠️ **当前只对管理员开放**（2026-10-28 暂定）：功能还在试，先让管理员自己用。
    要对外开放时，把依赖换成 `get_optional_user` 并把下面 `limit` 改成按登录态分档即可
    —— 匿名限流的分支（`_RATE_LIMIT_ANON` + 按 IP 计数）已经写好了，只是现在走不到。

    和 `/api/chat/lab/ask` 的区别：

    | | lab/ask | ask |
    |---|---|---|
    | 能调参 | 是（topK / kind / 阈值） | 否，只有问题 |
    | 返回 | 含调试用的 context | 只有答案 + 命中的标题 |

    实现上共用同一份 `chain.ask()` —— 实验室调的什么，用户拿到的就是什么，
    不会出现"实验室效果好、上线效果差"的两套逻辑。
    """
    chain = _lab_chain()   # 同一个模块，不是两套实现

    key = _client_key(request, user)
    limit = _RATE_LIMIT_USER if user else _RATE_LIMIT_ANON
    if not _rate_allow(key, limit):
        raise HTTPException(status_code=429, detail="问得有点快，请稍后再试")

    try:
        # with_context=False：调试用的「实际发给模型的资料」不给前台，只在 lab 接口返回
        result = chain.ask(body.question, with_context=False)
    except RuntimeError as exc:
        # 模型没配 key / 调用失败：503 + 中文原因，前端据此提示「客服暂不可用」
        raise HTTPException(status_code=503, detail=str(exc)) from exc

    _log.info("客服问答：len=%d 命中=%d", len(body.question), len(result["hits"]))
    return ok({
        "answer": result["answer"],
        # 命中的标题给前端做「参考资料」小字展示（可选渲染），不暴露正文和分数
        "hits": [{"title": h["title"], "kind": h["kind"]} for h in result["hits"]],
        "model": result["model"],
    })
