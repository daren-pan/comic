"""把任务结果主动推给 QQ（任务收尾时直接发，不再靠用户轮询）。

两条通道，默认走第一条：
- `qqofficial`：**QQ 官方机器人 API**（`TB_PUSH_CHANNEL=qqofficial`）。带 appid/secret
  换 `access_token`（2 小时，提前 60 秒刷新），再 POST
  `/v2/users/{openid}/messages` 发**主动消息**——不需要用户先发一句话。
- `onebot`：NapCat 的 OneBot HTTP（2026-11-23 起 NapCat 已从部署里移除，只为回滚保留）。

为什么不再用轮询：用户不想每隔几秒问一次「进度」。任务收尾时由服务主动发一条消息，
QQ 里直接看到结果即可；`/command` 的「进度」仍然保留，用于临时查询。

官方 API 的几条硬约束（踩过才知道）：
- 取 token 的接口**失败也返回 HTTP 200**，只能看响应体里有没有 `access_token`；
- 主动消息受用户客户端「允许主动发送」开关控制，关了就 `40034105`/`40054013`；
- 文本超长会被 `40054007` 拒收，所以这里先截断。
"""

from __future__ import annotations

import json
import threading
import time
import urllib.error
import urllib.request
from typing import Any

from . import config

#: access_token 缓存（多线程共用一个 worker，加锁足够）
_TOKEN_LOCK = threading.Lock()
_TOKEN: dict[str, Any] = {"value": "", "expires_at": 0.0}


def _post_json(url: str, payload: dict, headers: dict | None = None) -> tuple[int, str]:
    data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=data,
        headers={"Content-Type": "application/json; charset=utf-8", **(headers or {})},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=config.PUSH_TIMEOUT) as resp:
            return resp.getcode(), resp.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as exc:
        # 400 也带响应体（官方错误码在 body 里），不能直接丢
        return exc.code, exc.read().decode("utf-8", "replace")


def _log(line: str) -> None:
    """同时打屏和落文件：服务常驻运行时 stdout 会被缓冲，文件更可靠。"""
    print(line, flush=True)
    try:
        path = config.RUN_ROOT / "notify.log"
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as fh:
            fh.write(line + "\n")
    except OSError:
        pass


def _fit(text: str) -> str:
    """按官方单条文本上限截断，留一句指路文案。"""
    limit = max(80, config.PUSH_MAX_CHARS)
    if len(text) <= limit:
        return text
    tail = "\n…（已截断，发「进度」看全文）"
    return text[: max(1, limit - len(tail))].rstrip() + tail


# ---------------- 官方 API 通道 ----------------

def _access_token(force: bool = False) -> str:
    """取（并缓存）官方 access_token；失败抛 RuntimeError。"""
    now = time.time()
    with _TOKEN_LOCK:
        if not force and _TOKEN["value"] and now < float(_TOKEN["expires_at"]) - 60:
            return str(_TOKEN["value"])

        code, body = _post_json(
            config.QQ_TOKEN_URL,
            {"appId": config.QQ_APPID, "clientSecret": config.QQ_SECRET},
        )
        try:
            data = json.loads(body)
        except ValueError:
            data = {}
        token = str(data.get("access_token") or "")
        if not token:
            raise RuntimeError(f"取 access_token 失败：http={code} body={body[:200]}")
        _TOKEN["value"] = token
        _TOKEN["expires_at"] = now + int(data.get("expires_in") or 600)
        return token


def _push_qqofficial(text: str) -> bool:
    if not (config.QQ_APPID and config.QQ_SECRET and config.QQ_OPENIDS):
        _log("[notify] 未配置 TB_QQ_APPID / TB_QQ_SECRET / TB_QQ_OPENIDS，跳过")
        return False

    body_text = _fit(text)
    try:
        token = _access_token()
    except Exception as exc:  # noqa: BLE001 —— 推送失败不能影响任务本身
        _log(f"[notify] 取 token 失败：{type(exc).__name__}: {exc}")
        return False

    ok = False
    base = config.QQ_API_BASE.rstrip("/")
    for openid in config.QQ_OPENIDS:
        url = f"{base}/v2/users/{openid}/messages"
        try:
            code, body = _post_json(
                url,
                {"content": body_text, "msg_type": 0},
                {"Authorization": f"QQBot {token}"},
            )
            if code == 401:  # token 过期/被刷新：换一次再试
                token = _access_token(force=True)
                code, body = _post_json(
                    url,
                    {"content": body_text, "msg_type": 0},
                    {"Authorization": f"QQBot {token}"},
                )
        except Exception as exc:  # noqa: BLE001 —— 推送失败只记日志，绝不打断任务收尾
            _log(f"[notify] qqofficial:{openid} 推送失败：{type(exc).__name__}: {exc}")
            continue

        sent = code == 200 and '"id"' in body
        _log(f"[notify] qqofficial:{openid} -> {code} {body[:160]}")
        ok = ok or sent
    return ok


# ---------------- 遗留：NapCat / OneBot HTTP ----------------

def _push_onebot(text: str) -> bool:
    if not config.PUSH_TARGETS:
        _log("[notify] onebot 通道未配置 TB_PUSH_TARGETS，跳过")
        return False
    if not config.PUSH_BASE:
        _log("[notify] onebot 通道未配置 TB_PUSH_BASE，跳过")
        return False

    ok = False
    for target in config.PUSH_TARGETS:
        kind, _, ident = target.partition(":")
        ident = ident.strip()
        if not ident:
            continue
        try:
            if kind == "group":
                code, body = _post_json(
                    config.PUSH_BASE.rstrip("/") + "/send_group_msg",
                    {"group_id": int(ident), "message": text},
                )
            else:
                code, body = _post_json(
                    config.PUSH_BASE.rstrip("/") + "/send_private_msg",
                    {"user_id": int(ident), "message": text},
                )
            sent = code == 200 and '"status":"ok"' in body.replace(" ", "")
            _log(f"[notify] {target} -> {code} {body[:120]}")
            ok = ok or sent
        except Exception as exc:  # noqa: BLE001 —— 同上，推送失败不能影响任务
            _log(f"[notify] {target} 推送失败：{type(exc).__name__}: {exc}")
    return ok


def push_text(text: str) -> bool:
    """推一条纯文本到所有配置的会话；任一成功即返回 True。"""
    if not config.PUSH_ENABLED:
        _log("[notify] PUSH_ENABLED=false，跳过")
        return False
    text = (text or "").strip()
    if not text:
        return False
    if config.PUSH_CHANNEL == "onebot":
        return _push_onebot(text)
    return _push_qqofficial(text)
