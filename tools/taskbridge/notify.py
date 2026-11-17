"""把任务结果主动推给 QQ（经 NapCat 的 OneBot HTTP 接口）。

为什么不再用轮询：用户不想每隔几秒问一次「进度」。任务收尾时由服务主动发一条消息，
QQ 里直接看到结果即可；`/command` 的「进度」仍然保留，用于临时查询。

依赖：NapCat 开了 OneBot HTTP 服务（`httpServers`），地址形如
`http://comic-napcat:3000`，带同一个 token 做 Bearer 鉴权。
"""

from __future__ import annotations

import json
import urllib.error
import urllib.request

from . import config


def _post(path: str, payload: dict) -> tuple[int, str]:
    url = config.PUSH_BASE.rstrip("/") + path
    data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=data,
        headers={
            "Content-Type": "application/json; charset=utf-8",
            "Authorization": f"Bearer {config.PUSH_TOKEN}",
        },
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=config.PUSH_TIMEOUT) as resp:
        return resp.getcode(), resp.read().decode("utf-8", "replace")


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


def push_text(text: str) -> bool:
    """推一条纯文本到所有配置的会话；任一成功即返回 True。"""
    if not config.PUSH_ENABLED or not config.PUSH_TARGETS:
        _log("[notify] 未启用或未配置目标，跳过")
        return False

    ok = False
    for target in config.PUSH_TARGETS:
        kind, _, ident = target.partition(":")
        ident = ident.strip()
        if not ident:
            continue
        try:
            if kind == "group":
                code, body = _post("/send_group_msg", {"group_id": int(ident), "message": text})
            else:
                code, body = _post("/send_private_msg", {"user_id": int(ident), "message": text})
            sent = code == 200 and '"status":"ok"' in body.replace(" ", "")
            _log(f"[notify] {target} -> {code} {body[:120]}")
            ok = ok or sent
        except (urllib.error.URLError, OSError, ValueError) as exc:
            _log(f"[notify] {target} 推送失败：{type(exc).__name__}: {exc}")
    return ok
