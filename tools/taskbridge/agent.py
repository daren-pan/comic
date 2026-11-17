"""调用 coding agent（opencode CLI）执行一次改动任务。

只做三件事：写 opencode 配置、起子进程、收输出。
成败判定**不在这里**——由 `workspace.validate_changes` 用 git diff 硬校验。
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
from pathlib import Path

from . import config


class AgentError(RuntimeError):
    pass


def read_api_key() -> str:
    """从 chat-service 的 .env 里取 zen key，避免在别处再存一份密钥。"""
    key = os.environ.get("OPENCODE_GO_KEY", "").strip()
    if key:
        return key
    if not config.KEY_ENV_FILE.is_file():
        raise AgentError(f"找不到密钥来源文件：{config.KEY_ENV_FILE}")
    for line in config.KEY_ENV_FILE.read_text(encoding="utf-8", errors="replace").splitlines():
        if line.startswith(config.KEY_ENV_NAME + "="):
            return line.split("=", 1)[1].strip().strip('"').strip("'")
    raise AgentError(f"{config.KEY_ENV_FILE} 里没有 {config.KEY_ENV_NAME}")


def opencode_command() -> str:
    """定位 opencode 可执行文件。

    npm 全局安装出来的是 `.cmd` 批处理壳子，**命令行里的换行会被 cmd.exe 截断**，
    导致多行需求只剩第一行（实测踩过）。所以优先解析壳子里指向的真实 `opencode.exe`。
    """
    exe = shutil.which(config.OPENCODE_BIN) or config.OPENCODE_BIN
    if not Path(exe).exists() and not shutil.which(exe):
        raise AgentError(f"找不到 opencode 可执行文件：{config.OPENCODE_BIN}")

    if exe.lower().endswith((".cmd", ".bat")):
        try:
            shim_path = Path(exe)
            shim = shim_path.read_text(encoding="utf-8", errors="replace")
            # 壳子里常写 `"%dp0%\node_modules\...\opencode.exe"`，要先把 %dp0% 换成壳子所在目录
            for var in ("%~dp0", "%dp0%", "%dp0%"):
                shim = shim.replace(var, str(shim_path.parent) + "\\")
            for token in shim.replace('"', " ").split():
                if token.lower().endswith("opencode.exe") and Path(token).exists():
                    return str(Path(token))
        except OSError:
            pass
    return exe


def _flatten(prompt: str) -> str:
    """把多行需求压成单行：命令行传参对换行不安全（.cmd 壳子会截断）。"""
    return " ".join(line.strip() for line in prompt.replace("\r", "\n").split("\n") if line.strip())


def write_opencode_config(worktree: Path) -> None:
    """在副本里写项目级配置：provider 指向 zen 网关，key 从环境变量取（不落盘）。"""
    cfg = {
        "$schema": "https://opencode.ai/config.json",
        "provider": {
            "opencode-zen": {
                "npm": "@ai-sdk/openai-compatible",
                "name": "OpenCode Zen",
                "options": {
                    "baseURL": config.ZEN_BASE_URL,
                    "apiKey": "{env:OPENCODE_GO_KEY}",
                    "headers": {"x-opencode-session": "{env:OPENCODE_GO_SESSION}"},
                },
                "models": {
                    config.OPENCODE_MODEL.split("/", 1)[-1]: {
                        "name": config.OPENCODE_MODEL.split("/", 1)[-1]
                    }
                },
            }
        },
    }
    (worktree / "opencode.json").write_text(
        json.dumps(cfg, ensure_ascii=False, indent=2), encoding="utf-8"
    )


def run_task(worktree: Path, prompt: str, task_id: str) -> tuple[str, int]:
    """执行一次任务，返回 (日志尾部, 退出码)。超时抛 AgentError。"""
    key = read_api_key()
    env = dict(os.environ)
    env["OPENCODE_GO_KEY"] = key
    env["OPENCODE_GO_SESSION"] = f"tb-{task_id}"
    # ⚠️ opencode 默认把日志/缓存写到 `~/.local/share/opencode`，而本服务可能跑在
    # 受限沙箱或只读 HOME 下（实测 Windows 沙箱会 PermissionError，Windows 报
    # `FileSystem.open` 直接退出）。把 XDG 目录重定向到仓库内，既绕开权限问题，
    # 也让产物可追踪。
    oc_home = config.RUN_ROOT / "ocdata"
    env["XDG_DATA_HOME"] = str(oc_home / "share")
    env["XDG_CACHE_HOME"] = str(oc_home / "cache")
    env["XDG_CONFIG_HOME"] = str(oc_home / "config")
    env.setdefault("HOME", os.environ.get("USERPROFILE", ""))

    cmd = [
        opencode_command(),
        "run",
        "--auto",
        "--dir",
        str(worktree),
        "-m",
        config.OPENCODE_MODEL,
        _flatten(prompt),
    ]
    try:
        proc = subprocess.run(
            cmd,
            cwd=str(worktree),
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=config.TASK_TIMEOUT,
            env=env,
        )
    except subprocess.TimeoutExpired as exc:
        raise AgentError(f"任务超时（>{config.TASK_TIMEOUT}s）已终止") from exc

    tail = "\n".join(((proc.stdout or "") + (proc.stderr or "")).splitlines()[-60:])
    return tail, proc.returncode
