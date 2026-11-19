"""单消费者任务队列 + 分支工作流。

状态机：queued → running → awaiting_review → applying → applied
                                   ↘ discarded        ↘ failed

为什么串行（并发=1）：任务直接在主仓库工作区里改（分支模型），
两个任务同时跑必然互相踩；而且 coding agent 每个进程都吃内存。
"""

from __future__ import annotations

import queue
import threading
import traceback
from pathlib import Path

from . import agent, notify, workspace
from .store import TaskStore

_QUEUE: "queue.Queue[str]" = queue.Queue()
_STARTED = False

#: 服务自己写的配置文件名，收尾时删掉
_INTERNAL = "opencode.json"


def start_worker(store: TaskStore) -> None:
    global _STARTED
    if _STARTED:
        return
    _STARTED = True
    interrupted = store.mark_interrupted()
    if interrupted:
        print(f"[taskbridge] 启动清理：{interrupted} 个中断任务已标记失败")
    t = threading.Thread(target=_loop, args=(store,), name="taskbridge-worker", daemon=True)
    t.start()


def submit(task_id: str) -> None:
    _QUEUE.put(task_id)


def _loop(store: TaskStore) -> None:
    while True:
        task_id = _QUEUE.get()
        try:
            _run_one(store, task_id)
        except Exception:
            traceback.print_exc()
            store.update(task_id, status="failed", error="worker 内部异常，见服务日志")
        finally:
            _QUEUE.task_done()


def _paths_from_status(status: str) -> set[str]:
    """把 `git status --porcelain` 输出解析成路径集合。"""
    out = set()
    for line in status.splitlines():
        if len(line) < 4:
            continue
        p = line[3:].strip()
        if " -> " in p:
            p = p.split(" -> ", 1)[1]
        out.add(p.strip('"'))
    return out


def _run_one(store: TaskStore, task_id: str) -> None:
    task = store.get(task_id)
    if not task or task["status"] != "queued":
        return

    store.update(task_id, status="running")
    if task.get("mode") == "ask":
        _run_ask(store, task)
        return
    branch = ""
    original = "main"
    baseline: set[str] = set()
    try:
        baseline = _paths_from_status(workspace.baseline_status())
        branch, original = workspace.start_branch(task_id)

        agent.write_opencode_config(workspace.config.REPO_ROOT)
        log_tail, code, _stdout = agent.run_task(workspace.config.REPO_ROOT, task["prompt"], task_id)
        store.update(task_id, log_tail=log_tail[-6000:])

        all_changed = _paths_from_status(workspace.baseline_status())
        # 只认「这个任务带来的」改动，任务开始前就脏的文件（你自己的在改的）不碰
        files = sorted(p for p in all_changed if p not in baseline and p != _INTERNAL)
        skipped = sorted(p for p in all_changed if p in baseline)

        workspace.validate_changes(files, task["allowed_paths"])
        if skipped:
            # 只写日志：这些是你自己正在改的文件，不该出现在给用户看的文案里
            store.update(task_id, log_tail=(log_tail + f"\n[baseline] 未纳入：{', '.join(skipped)}")[-6000:])
        store.update(
            task_id,
            status="awaiting_review",
            branch=branch,
            files=files,
            diff_stat=workspace.diff_stat(files),
            diff_text=workspace.diff_text(files)[-20000:],
            error="" if code == 0 else f"agent 退出码 {code}（改动已产出，请人工判断）",
        )
        _notify_review(store, task_id)
    except workspace.BridgeError as exc:
        _cleanup_failed(branch, original, baseline)
        store.update(task_id, status="failed", error=str(exc))
        notify.push_text(f"{task_id} 失败：{exc}")
    except agent.AgentError as exc:
        _cleanup_failed(branch, original, baseline)
        store.update(task_id, status="failed", error=str(exc))
        notify.push_text(f"{task_id} 失败：{exc}")
    except Exception as exc:  # noqa: BLE001 —— 任何意外都要落成 failed，不能卡在 running
        _cleanup_failed(branch, original, baseline)
        store.update(task_id, status="failed", error=f"{type(exc).__name__}: {exc}")
        notify.push_text(f"{task_id} 失败：{type(exc).__name__}: {exc}")


def _notify_review(store: TaskStore, task_id: str) -> None:
    """任务改成待审后主动推一条消息（替代轮询）。"""
    task = store.get(task_id)
    if not task:
        return
    files = "\n".join(f"· {f}" for f in task["files"]) or "· （无）"
    text = (
        f"{task_id} 改完了，等你确认：\n{files}\n"
        f"改动量：{task['diff_stat'] or ''}\n"
        f"回复「应用 {task_id}」提交，「丢弃 {task_id}」放弃。"
    )
    notify.push_text(text)



#: 只读问答的任务前缀：明确禁止改动，避免「问问题却改了文件」
ASK_PREFIX = (
    "只读任务：不要修改、创建或删除任何文件，也不要执行改变仓库状态的命令。"
    "请阅读代码后直接回答问题，答案用中文、简洁分点：\n"
)


def _clean_answer(stdout: str, tail: str) -> str:
    """从 opencode 输出里抽出可读答案：去掉 ANSI 与工具命令行。"""
    import re as _re

    text = _re.sub(r"\x1b\[[0-9;]*[A-Za-z]", "", stdout or "")
    lines = []
    for line in text.splitlines():
        s = line.strip()
        if not s or s.startswith("$") or s.startswith(">"):
            continue
        lines.append(line.rstrip())
    answer = "\n".join(lines).strip()
    return answer or tail or "（没有拿到答案）"


def _run_ask(store: TaskStore, task: dict) -> None:
    """只读问答：不改文件、不要求 diff；答案直接推给用户。"""
    task_id = task["id"]
    branch, original = workspace.start_branch(task_id)
    try:
        baseline = _paths_from_status(workspace.baseline_status())
        agent.write_opencode_config(workspace.config.REPO_ROOT)
        tail, code, stdout = agent.run_task(
            workspace.config.REPO_ROOT, ASK_PREFIX + task["prompt"], task_id
        )
        answer = _clean_answer(stdout, tail)

        # 万一 agent 还是改了文件：先还原，再切回 main
        changed = [
            p for p in _paths_from_status(workspace.baseline_status())
            if p not in baseline and p != _INTERNAL
        ]
        workspace.abort_branch(changed, original)
        Path(workspace.config.REPO_ROOT / _INTERNAL).unlink(missing_ok=True)

        store.update(task_id, status="answered", answer=answer, files=[], error="")
        notify.push_text(f"{task_id} 回答：\n{answer[:1500]}")
    except Exception as exc:  # noqa: BLE001
        workspace.abort_branch([], original)
        store.update(task_id, status="failed", error=f"{type(exc).__name__}: {exc}")
        notify.push_text(f"{task_id} 查询失败：{exc}")


def _cleanup_failed(branch: str, original: str, baseline: set[str]) -> None:
    """失败时把工作区还原干净：只还原本任务新增的改动，保留任务前就脏的文件。"""
    try:
        current = _paths_from_status(workspace.baseline_status())
        touched = sorted(p for p in current if p not in baseline and p != _INTERNAL)
        Path(workspace.config.REPO_ROOT / _INTERNAL).unlink(missing_ok=True)
        if branch:
            workspace.abort_branch(touched, original)
        elif touched:
            workspace.git(workspace.config.REPO_ROOT, "checkout", "--", *touched, check=False)
            workspace.git(workspace.config.REPO_ROOT, "clean", "-fd", "--", *touched, check=False)
    except Exception:  # 清理失败不能盖住原始错误
        traceback.print_exc()


def apply_task(store: TaskStore, task_id: str, commit_message: str) -> dict:
    """确认后落地：分支提交 → main 快进 → 删分支 → 推远端。

    推送失败不回滚本地提交，只把错误回报到 QQ（人工补一次 push 即可）。
    """
    task = store.get(task_id)
    if not task:
        raise workspace.BridgeError("任务不存在")
    if task["status"] != "awaiting_review":
        raise workspace.BridgeError(f"当前状态 {task['status']}，只有 awaiting_review 可以应用")

    store.update(task_id, status="applying")
    try:
        commit, pushed, push_msg = workspace.finish_branch(
            task["branch"], task["files"], commit_message
        )
    except workspace.BridgeError as exc:
        store.update(task_id, status="awaiting_review", error=str(exc))
        raise
    finally:
        Path(workspace.config.REPO_ROOT / _INTERNAL).unlink(missing_ok=True)

    store.update(
        task_id,
        status="applied",
        commit_hash=commit,
        commit_msg=commit_message,
        error="" if pushed else f"推送失败：{push_msg}",
        push_ok=1 if pushed else 0,
        push_error="" if pushed else push_msg,
    )
    if pushed:
        notify.push_text(f"{task_id} 已提交并推送（commit {commit}）：{commit_message}")
    else:
        notify.push_text(
            f"{task_id} 已提交到本地（commit {commit}），但推送远端失败：\n"
            f"{push_msg}\n\n"
            f"本地提交还在，处理方式：登录服务器 `cd {workspace.config.REPO_ROOT} && git push`；"
            f"若远端有新提交，先 `git pull --rebase` 再推。"
        )
    return store.get(task_id)  # type: ignore[return-value]


def discard_task(store: TaskStore, task_id: str) -> dict:
    task = store.get(task_id)
    if not task:
        raise workspace.BridgeError("任务不存在")
    if task["status"] in {"applied", "discarded", "failed", "answered"}:
        raise workspace.BridgeError(f"任务已结束（{task['status']}）")

    workspace.abort_branch(task["files"], "main")
    Path(workspace.config.REPO_ROOT / _INTERNAL).unlink(missing_ok=True)
    store.update(task_id, status="discarded")
    return store.get(task_id)  # type: ignore[return-value]
