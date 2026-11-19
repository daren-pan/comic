"""git 操作：分支工作流（不再用副本）。

模型：每个任务在主仓库里开一个分支 `tb/<任务号>`，agent 直接在工作区改；
确认后在该分支上提交，再把 main 快进过去并删分支；丢弃则还原改动、切回 main。

为什么这么改（用户决定）：分支保留完整历史，回滚只需 `git branch -D`。
代价要说清楚——**任务期间主仓库工作区就是改动现场**：
  · 别人（或你）同时编辑同一文件会互相影响；
  · 本地跑着的服务会立刻看到 agent 的半成品改动。

安全阀仍然保留：
  · 任务开始前记录 HEAD 与工作区指纹，结束后只认「预期路径」内的改动；
  · apply 前拒绝覆盖你已经手改过的文件（提交时会把这部分一起带进去）。
"""

from __future__ import annotations

import subprocess
from pathlib import Path

from . import config

#: 服务自己写进仓库的文件（不属于 agent 的改动）
INTERNAL_FILES = {"opencode.json"}


class BridgeError(RuntimeError):
    """可预期的业务错误：消息会原样回给调用方（QQ 用户）。"""


def git(repo: Path, *args: str, check: bool = True) -> str:
    proc = subprocess.run(
        ["git", *args],
        cwd=str(repo),
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=300,
    )
    if check and proc.returncode != 0:
        raise BridgeError(f"git {' '.join(args)} 失败：{(proc.stderr or proc.stdout).strip()[:400]}")
    # ⚠️ 只能去尾部换行：`git status --porcelain` 首行以空格开头（` M path`），
    # 用 `.strip()` 会削掉那个空格，导致列位移、路径少首字符（deploy → eploy）。
    return (proc.stdout or "").rstrip("\n")


def current_branch() -> str:
    return git(config.REPO_ROOT, "rev-parse", "--abbrev-ref", "HEAD")


def branch_for(task_id: str) -> str:
    return f"tb/{task_id}"


# ---------------- 分支生命周期 ----------------

def start_branch(task_id: str) -> tuple[str, str]:
    """建并切到任务分支，返回 (任务分支, 原分支)。"""
    if current_branch() != "main":
        raise BridgeError(f"当前不在 main（在 {current_branch()}），请先切回 main 再提交任务")

    branch = branch_for(task_id)
    git(config.REPO_ROOT, "branch", "-D", branch, check=False)  # 残留就先删
    git(config.REPO_ROOT, "checkout", "-b", branch)
    return branch, "main"


def push_main() -> tuple[bool, str]:
    """把本地 main 推到远端，返回 (是否成功, 说明/错误)。

    刻意**不抛异常**：本地提交已经完成，推送失败只是"远端还没同步"，
    属于可恢复状态 —— 让调用方把错误回报到 QQ，人工补一次 push 即可。
    """
    if not config.GIT_PUSH_ENABLED:
        return True, "已关闭自动推送（TB_GIT_PUSH=false）"

    ref = f"HEAD:{config.GIT_BRANCH}"
    try:
        proc = subprocess.run(
            ["git", "push", config.GIT_REMOTE, ref],
            cwd=str(config.REPO_ROOT),
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=config.GIT_PUSH_TIMEOUT,
        )
    except subprocess.TimeoutExpired:
        return False, f"git push 超时（超过 {config.GIT_PUSH_TIMEOUT}s），远端可能不可达"

    if proc.returncode == 0:
        return True, f"已推送 {config.GIT_REMOTE}/{config.GIT_BRANCH}"

    detail = (proc.stderr or proc.stdout or "").strip()
    # 去掉 git 自己加的提示行，只留第一段可读原因
    detail = "\n".join(line for line in detail.splitlines() if not line.startswith("hint:"))
    return False, (detail[:500] or f"git push 退出码 {proc.returncode}")


def finish_branch(branch: str, files: list[str], commit_message: str) -> tuple[str, bool, str]:
    """在任务分支上提交这些文件，把 main 快进过去，再推远端。

    返回 `(commit, 是否已推送, 推送说明)` —— 推送失败不影响本地提交。
    """
    git(config.REPO_ROOT, "add", "-A", "--", *files)
    git(config.REPO_ROOT, "commit", "-m", commit_message)
    commit = git(config.REPO_ROOT, "rev-parse", "--short", "HEAD")

    git(config.REPO_ROOT, "checkout", "main")
    merge = subprocess.run(
        ["git", "merge", "--ff-only", branch],
        cwd=str(config.REPO_ROOT),
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    if merge.returncode != 0:
        # 极端情况：任务期间有人在 main 上提交了，快进不了
        git(config.REPO_ROOT, "branch", "-D", branch, check=False)
        raise BridgeError("main 在任务期间有了新提交，无法快进合并；改动仍在任务分支上，请手动处理")

    git(config.REPO_ROOT, "branch", "-D", branch, check=False)
    pushed, push_msg = push_main()
    return commit, pushed, push_msg


def abort_branch(files: list[str], original: str = "main") -> None:
    """丢弃：还原这些文件的改动、删掉新增文件、切回 main 并删分支。"""
    branch = current_branch()
    if branch.startswith("tb/"):
        if files:
            git(config.REPO_ROOT, "checkout", "--", *files, check=False)
            # 新增文件（未跟踪）用 clean 清掉
            git(config.REPO_ROOT, "clean", "-fd", "--", *files, check=False)
    if branch != original:
        git(config.REPO_ROOT, "checkout", original, check=False)
        git(config.REPO_ROOT, "branch", "-D", branch, check=False)


# ---------------- 改动采集与校验 ----------------

def changed_files() -> list[str]:
    """采集工作区全部改动（含新增/删除/重命名），排除服务自己的配置文件。

    用 `git status --porcelain` 而不是 `git diff`：`diff` 看不到未跟踪的新文件。
    格式固定为 `XY<空格>路径`，所以从第 4 个字符开始取；重命名取箭头右侧。
    """
    out = git(config.REPO_ROOT, "status", "--porcelain", "--untracked-files=all")
    files: list[str] = []
    for line in out.splitlines():
        if len(line) < 4:
            continue
        path = line[3:].strip()
        if " -> " in path:
            path = path.split(" -> ", 1)[1]
        path = path.strip('"')
        if path in INTERNAL_FILES:
            continue
        files.append(path)
    return files


def diff_text(files: list[str]) -> str:
    if not files:
        return ""
    git(config.REPO_ROOT, "add", "-N", "--", *files, check=False)
    return git(config.REPO_ROOT, "--no-pager", "diff", "HEAD", "--", *files)


def diff_stat(files: list[str]) -> str:
    if not files:
        return ""
    git(config.REPO_ROOT, "add", "-N", "--", *files, check=False)
    return git(config.REPO_ROOT, "diff", "--stat", "HEAD", "--", *files)


def validate_changes(files: list[str], allowed_paths: list[str]) -> None:
    """硬校验：这是「防 agent 谎报 / 跑飞」的唯一可信来源，必须跑在模型输出之外。"""
    if not files:
        raise BridgeError("agent 没有产生任何改动（diff 为空）—— 视为失败")
    if len(files) > config.MAX_FILES:
        raise BridgeError(f"改动文件过多（{len(files)} > {config.MAX_FILES}），疑似跑飞")

    for f in files:
        norm = f.replace("\\", "/")
        for bad in config.FORBIDDEN_PREFIXES:
            if norm.startswith(bad):
                raise BridgeError(f"改动了被禁止的路径：{norm}")
        if allowed_paths and not any(
            norm == p or norm.startswith(p.rstrip("/") + "/") for p in allowed_paths
        ):
            raise BridgeError(f"改动了未授权路径：{norm}（允许：{', '.join(allowed_paths)}）")


def baseline_status() -> str:
    """任务开始前的工作区快照：用于识别「哪些改动是这个任务带来的」。"""
    return git(config.REPO_ROOT, "status", "--porcelain", "--untracked-files=all")
