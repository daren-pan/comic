"""把「一句话」翻译成 TaskBridge 的动作，并生成可直接回给用户的文本。

为什么要有这一层：Dify 的 Chatflow 里每多一个 HTTP 节点 + 条件分支，维护成本就翻一倍。
这里把「提交 / 进度 / 应用 / 丢弃」四件事收在一个入口，Dify 只需要一个 HTTP 节点，
返回的 `reply` 直接当答案回给 QQ 即可。

命令语法（任务号可省略，省略时用「最近一条」）：
    应用                → 提交最近一条待确认的任务
    应用 A7F3           → 提交指定任务
    应用 docs(web): 说明 → 提交最近一条，并用你给的提交信息
    进度 / 进度 A7F3    → 查状态
    丢弃 / 丢弃 A7F3    → 放弃并删分支
    帮助                → 用法说明
    其它任意文本         → 当作新任务提交
"""

from __future__ import annotations

import re
from typing import Any

from . import config, worker
from .store import TaskStore

RE_TASK_ID = re.compile(r"^([0-9A-Fa-f]{8})\b\s*(.*)$", re.DOTALL)
USAGE = (
    "我可以改代码/文档。用法：\n"
    "1) 直接说要改什么，例如：把首页轮播间隔改成 5 秒\n"
    "2) 应用 —— 提交最近一次改动（也可以写「应用 A7F3」）\n"
    "3) 丢弃 —— 放弃最近一次改动\n"
    "4) 进度 —— 看最近一次任务的进展"
)

_STATUS_TEXT = {
    "queued": "排队中",
    "running": "执行中（agent 正在改）",
    "awaiting_review": "改完了，等你确认",
    "applying": "正在提交",
    "applied": "已提交",
    "discarded": "已丢弃",
    "failed": "失败",
}

#: 命令词 → 规范名
_VERBS = {
    "应用": "apply",
    "提交": "apply",
    "apply": "apply",
    "丢弃": "discard",
    "放弃": "discard",
    "discard": "discard",
    "进度": "status",
    "状态": "status",
    "status": "status",
}


def handle(store: TaskStore, text: str) -> dict[str, Any]:
    """入口：返回 {reply, task_id?, status?}。"""
    text = (text or "").strip()
    if not text:
        return {"reply": USAGE}
    if text.strip("？?。.!！ ") in ("帮助", "help"):
        return {"reply": USAGE}

    verb, rest = _split_verb(text)
    if verb == "status":
        return _status(store, rest)
    if verb == "apply":
        return _apply(store, rest)
    if verb == "discard":
        return _discard(store, rest)

    return _submit(store, text)


def _split_verb(text: str) -> tuple[str, str]:
    """识别「动词 [任务号] [其余]」。返回 (规范动词, 其余)；不是命令则返回 ("", 原文)。

    只在**形状像命令**时才认，避免把「提交按钮点了没反应，帮我修一下」这种需求误判成提交。
    """
    parts = text.split(maxsplit=1)
    head = parts[0].strip("，,。.！!？? ")
    verb = _VERBS.get(head.lower()) if head.isascii() else _VERBS.get(head)
    if not verb:
        return "", text

    rest = parts[1].strip() if len(parts) > 1 else ""
    if len(text) > 60:  # 太长的多半是需求描述，不是命令
        return "", text
    if rest and not RE_TASK_ID.match(rest):
        # 应用可以带自定义提交信息（Conventional Commits 才有冒号）；其它动词只认任务号
        if not (verb == "apply" and ":" in rest):
            return "", text
    return verb, rest


def _pick(store: TaskStore, rest: str) -> tuple[str, str]:
    """从「其余」里解析出任务号与附加文本；没有任务号就取最近一条待确认任务。"""
    rest = rest.strip()
    m = RE_TASK_ID.match(rest)
    if m:
        return m.group(1).upper(), (m.group(2) or "").strip()
    task = store.latest("awaiting_review")
    if task:
        return task["id"], rest
    return "", rest


# ---------------- 动作实现 ----------------

def _submit(store: TaskStore, text: str) -> dict[str, Any]:
    task = store.create("code", text, [])
    worker.submit(task["id"])
    return {
        "reply": f"已受理 {task['id']}，正在改。改完我会直接发消息给你（也可以发「进度」查）。",
        "task_id": task["id"],
        "status": "queued",
    }


def _status(store: TaskStore, rest: str) -> dict[str, Any]:
    task_id, _ = _pick(store, rest)
    if not task_id:
        recent = store.list(1)
        if not recent:
            return {"reply": "还没有任何任务。"}
        task_id = recent[0]["id"]

    task = store.get(task_id)
    if not task:
        return {"reply": f"没有找到任务 {task_id}，确认下编号。"}

    status = task["status"]
    if status == "awaiting_review":
        files = "\n".join(f"· {f}" for f in task["files"]) or "· （无）"
        return {
            "reply": (
                f"{task_id} 改完了，等你确认：\n{files}\n"
                f"改动量：{task['diff_stat'] or ''}\n"
                f"回复「应用」提交，或「丢弃」放弃。"
            ),
            "task_id": task_id,
            "status": status,
        }
    if status == "applied":
        return {
            "reply": f"{task_id} 已提交（commit {task['commit_hash']}）。",
            "task_id": task_id,
            "status": status,
        }
    if status == "failed":
        return {
            "reply": f"{task_id} 失败：{task['error'] or '未知原因'}",
            "task_id": task_id,
            "status": status,
        }
    return {
        "reply": f"{task_id} 当前状态：{_STATUS_TEXT.get(status, status)}。",
        "task_id": task_id,
        "status": status,
    }


def _apply(store: TaskStore, rest: str) -> dict[str, Any]:
    task_id, message = _pick(store, rest)
    if not task_id:
        return {"reply": "现在没有待确认的任务。"}
    if not message:
        task = store.get(task_id) or {}
        message = _default_message(task_id, task.get("files") or [])
    try:
        task = worker.apply_task(store, task_id, message)
    except Exception as exc:  # BridgeError 等
        return {"reply": f"提交失败：{exc}", "task_id": task_id}
    return {
        "reply": (
            f"{task_id} 已提交（commit {task['commit_hash']}）：{message}\n"
            "改动已进主分支，需要上线就发「部署网页端」。"
        ),
        "task_id": task_id,
        "status": "applied",
    }


def _default_message(task_id: str, files: list[str]) -> str:
    """按改动文件推断 Conventional Commits 的类型与 scope。

    只改 Markdown 记 `docs(...)`，其余记 `chore(...)`；scope 取模块目录名。
    用户想更精确的说明时，直接写「应用 docs(web): …」即可覆盖。
    """
    scope_map = {
        "api-service": "api",
        "crawler-service": "crawler",
        "comic-core": "core",
        "comic-web": "web",
        "comic-front": "front",
        "comic-scheduler": "scheduler",
        "chat-service": "chat",
        "knowledge-mcp": "knowledge",
        "deploy": "deploy",
        "docs": "docs",
        "tools": "tools",
        "scripts": "tools",
    }
    scopes = {scope_map.get(f.split("/", 1)[0], "repo") for f in files if "/" in f}
    scope = scopes.pop() if len(scopes) == 1 else "repo"
    only_docs = bool(files) and all(f.lower().endswith(".md") for f in files)
    kind = "docs" if only_docs else "chore"
    return f"{kind}({scope}): 应用任务 {task_id}"


def _discard(store: TaskStore, rest: str) -> dict[str, Any]:
    task_id, _ = _pick(store, rest)
    if not task_id:
        return {"reply": "现在没有待确认的任务。"}
    try:
        worker.discard_task(store, task_id)
    except Exception as exc:
        return {"reply": f"丢弃失败：{exc}", "task_id": task_id}
    return {"reply": f"{task_id} 已丢弃，分支和改动都清掉了。", "task_id": task_id, "status": "discarded"}
