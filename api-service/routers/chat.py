"""客服与 RAG 实验室的 HTTP 接口 —— **本层只做鉴权/限流/转发**，不跑模型。

## 为什么这里是网关而不是实现

RAG 全套依赖（langchain / chromadb / fastembed，80+ 个传递依赖）和 bge 模型常驻内存
都在独立容器 `comic-chat` 里 —— 塞进 api 镜像会让主站涨 400MB 并跟主站抢内存。
所以本模块的每个接口最终都只是一次内网 HTTP 调用（`_forward`）。

**鉴权为什么留在这一层**：`core/security.py` 是 api-service 的模块，搬不到别的服务；
chat-service 也不该知道「谁在问」。分工是：**api 认人，chat 认问题**。

## 五种错误分开报（排查时一眼定位）

| 情况 | 返回 | 含义 |
|---|---|---|
| chat-service 没起 / 网络不通 | 503 客服服务未启动 | 容器挂了或地址配错 |
| 超时（默认 40s） | 504 客服响应超时 | 模型卡住 / 上游慢 |
| 上游 5xx / 协议异常 | 502 客服服务异常 | 服务内部崩了 |
| 上游 4xx（如模型没配 key） | 原样透传 + 中文原因 | 配置问题，不是程序错 |
| 本层限流 | 429 | 问太快 |

## 谁能调

| 接口 | 门槛 |
|---|---|
| `POST /api/chat/ask` | `require_admin`（暂定，见该函数注释） |
| `GET /api/chat/lab/*` · `POST /api/chat/lab/*` | `require_admin` |
"""
from __future__ import annotations

import logging
import os
import time

import httpx
from fastapi import APIRouter, Depends, HTTPException, Request

from core.responses import ok
from core.security import require_admin
from schemas import ChatAskBody, ChatLabBody

router = APIRouter(tags=["chat"])
_log = logging.getLogger("comic.chat")

#: 默认开。要关就 `COMIC_CHAT_LAB=0`（关闭后这些路由根本不挂载，请求 404）。
_DISABLED_VALUES = {"0", "false", "no", "off"}

#: chat-service 地址。容器里是 `http://comic-chat:8001`（compose 服务名），
#: 本地直跑默认 `http://127.0.0.1:8001`。
CHAT_SERVICE_URL = os.environ.get(
    "COMIC_CHAT_SERVICE_URL", "http://127.0.0.1:8001"
).rstrip("/")

#: 转发超时。要比模型自身的 `timeout=30` 大一点，否则模型还没超时我们先断了。
CHAT_TIMEOUT = float(os.environ.get("COMIC_CHAT_TIMEOUT", "40"))

# ---- 公开客服接口的限流（内存滑动窗口，进程内）----
# 为什么放在 api 而不是 chat-service：chat 不认用户，拿不到账号/IP 的语义。
# ⚠️ 多副本部署时这条限流会失效（每个进程各算一份），届时必须换共享存储。
_RATE: dict[str, list[float]] = {}
_RATE_WINDOW = 3600
_RATE_LIMIT_USER = 60
_RATE_LIMIT_ANON = 15


def enabled() -> bool:
    """路由是否挂载（`main.py` 装配时问一次）。"""
    return os.environ.get("COMIC_CHAT_LAB", "1").strip().lower() not in _DISABLED_VALUES


def _forward(method: str, path: str, payload: dict | None = None) -> dict:
    """把请求转给 chat-service，并把各类失败映射成能看懂的中文。"""
    url = f"{CHAT_SERVICE_URL}{path}"
    try:
        resp = httpx.request(method, url, json=payload, timeout=CHAT_TIMEOUT)
    except httpx.TimeoutException as exc:
        # ⚠️ 必须排在 TransportError 之前：TimeoutException 是它的子类，
        # 顺序反了超时会被当成「连不上」，报错文案就误导人。
        raise HTTPException(status_code=504, detail="客服响应超时，请稍后再试") from exc
    except httpx.TransportError as exc:
        # 连接失败 / 连接被重置 / 协议中断，统一按「服务不可用」处理。
        # ⚠️ 只捕 ConnectError 是不够的：实测 Windows 上对一个**已关闭的端口**发请求，
        # 常常是先建连再被 RST，抛的是 `ReadError`（WinError 10054）而不是 ConnectError ——
        # 那样会掉进下面的 502 分支，提示变成「通信失败」，让人以为是服务崩了而不是没起。
        _log.warning("客服服务不可达：%s（%s）", url, type(exc).__name__)
        raise HTTPException(
            status_code=503,
            detail="客服服务未启动或地址不通（comic-chat）",
        ) from exc
    except httpx.HTTPError as exc:
        raise HTTPException(status_code=502, detail=f"客服服务通信失败：{exc}") from exc

    if resp.status_code >= 400:
        # 上游把中文原因放在 detail 里（例如「对话模型没有配置…」），原样透传
        detail = ""
        try:
            detail = str(resp.json().get("detail") or "")
        except Exception:   # noqa: BLE001 —— 上游返回的不是 JSON
            detail = resp.text[:200]
        status = resp.status_code if resp.status_code < 500 else 502
        raise HTTPException(status_code=status, detail=detail or "客服服务异常")

    try:
        return resp.json()
    except ValueError as exc:
        raise HTTPException(status_code=502, detail="客服服务返回了非 JSON 内容") from exc


def _rate_allow(key: str, limit: int) -> bool:
    """滑动窗口限流：窗口内次数没超就记账并放行。"""
    now = time.time()
    stamps = [t for t in _RATE.get(key, []) if now - t < _RATE_WINDOW]
    if len(stamps) >= limit:
        _RATE[key] = stamps
        return False
    stamps.append(now)
    _RATE[key] = stamps

    if len(_RATE) > 5000:
        for k in [k for k, v in _RATE.items() if not v or now - v[-1] > _RATE_WINDOW]:
            del _RATE[k]
    return True


def _client_key(request: Request, user: dict | None) -> str:
    """限流用的身份键：登录用户按账号，匿名按真实 IP。

    ⚠️ 必须优先读 `X-Forwarded-For`：容器里请求经过 nginx 反代，`request.client.host`
    拿到的是**nginx 的地址**（所有用户同一个）—— 直接用它，全站会共用一个额度。
    """
    if user:
        return f"u:{user.get('id')}"
    xff = request.headers.get("x-forwarded-for", "")
    ip = xff.split(",")[0].strip() if xff else ""
    if not ip and request.client:
        ip = request.client.host
    return f"ip:{ip or 'unknown'}"


# ---------------- RAG 实验室（管理员）----------------


@router.get("/api/chat/lab/status")
def lab_status(_admin: dict = Depends(require_admin)):
    """配置自检：向量后端、模型、索引位置、向量条数。**不回显任何密钥内容**。"""
    return ok(_forward("GET", "/lab/status"))


@router.post("/api/chat/lab/index")
def lab_index(_admin: dict = Depends(require_admin)):
    """全量重建索引（改过 faq.md 或采集了新作品之后跑）。"""
    return ok(_forward("POST", "/lab/index"))


@router.post("/api/chat/lab/search")
def lab_search(body: ChatLabBody, _admin: dict = Depends(require_admin)):
    """只检索、不调生成模型 —— 调试 RAG 时先用这个。"""
    return ok(_forward("POST", "/lab/search", body.model_dump()))


@router.post("/api/chat/lab/ask")
def lab_ask(body: ChatLabBody, _admin: dict = Depends(require_admin)):
    """完整问答，带实际发给模型的参考资料（`context`）。"""
    return ok(_forward("POST", "/lab/ask", body.model_dump()))


# ---------------- 客服问答（前台）----------------


@router.post("/api/chat/ask")
def chat_ask(
    body: ChatAskBody,
    request: Request,
    user: dict = Depends(require_admin),
):
    """**客服提问**（网站右侧悬浮球调的接口）。

    ⚠️ **当前只对管理员开放**（2026-10-28 暂定）：功能还在试，先让管理员自己用。
    要对外开放时，把依赖换成 `get_optional_user` 并把 `limit` 改成按登录态分档即可
    —— 匿名限流的分支（`_RATE_LIMIT_ANON` + 按 IP 计数）已经写好，只是现在走不到。
    """
    key = _client_key(request, user)
    limit = _RATE_LIMIT_USER if user else _RATE_LIMIT_ANON
    if not _rate_allow(key, limit):
        raise HTTPException(status_code=429, detail="问得有点快，请稍后再试")

    data = _forward("POST", "/ask", {
        "question": body.question,
        # 历史原样透传（上限已在 ChatAskBody 里卡过）；chat-service 据此决定要不要改写
        "history": [t.model_dump() for t in body.history],
    })
    _log.info(
        "客服问答：len=%d 历史=%d 改写=%s",
        len(body.question), len(body.history), bool(data.get("rewritten")),
    )
    return ok({
        "answer": data.get("answer", ""),
        "hits": data.get("hits") or [],
        # 改写结果回传前端：可以显示「理解为：xxx」，也是排查多轮是否生效的唯一线索
        "rewritten": data.get("rewritten"),
        "model": data.get("model", ""),
    })
