r"""运行期环境兜底：让 comic-chat 在受限 Windows 会话里也能直接启动。

## 为什么需要它

Chroma 的 Rust SQLite 绑定和 fastembed 都**直接使用系统临时目录**。在 DSH 之类的
受限会话里，`TEMP` 往往被指到工作区外的 `...\AppData\Local\Temp\dsh-xxx`，而该目录
对受限进程不可写：

- Chroma: `error returned from database: (code: 14) unable to open database file`
- fastembed: `PermissionError: [WinError 5] 拒绝访问`

Python 的 `tempfile` 在默认临时目录不可写时会回退到 cwd，但这两个原生库不走 Python
的回退逻辑。所以这里在导入 `rag`（chromadb / fastembed）之前，做两件事：

1. 探测 `TMP` / `TEMP` / `TMPDIR` 是否可写；都不可写就改用 `DATA_ROOT/tmp`，
   并把 `tempfile.tempdir` 一起指过去；
2. 开发态（能看到 `chat-service/pyproject.toml`）且未显式设置 `FASTEMBED_CACHE_PATH`
   时，把模型缓存固定到 `DATA_ROOT/fastembed_cache`，避免落到用户目录或站点包目录。

容器里 `/tmp` 可写，第 1 步不会触发；第 2 步因没有开发态 checkout 也不会改，
仍走 Dockerfile 预热的 `HF_HOME`。普通 Windows 终端里 `TEMP` 可写，同样不会改。

⚠️ 本模块必须在 `import chromadb` / `import fastembed` **之前**执行。入口见
`app.py`（服务）与 `cli.py`（命令行）；`scripts/dev.sh` 也会显式设置同样的环境变量，
两条路径互为兜底。
"""
from __future__ import annotations

import logging
import os
import tempfile
from pathlib import Path

from comic_core.paths import DATA_ROOT

logger = logging.getLogger("comic.chat")

_PREPARED = False
_PROBE_PREFIX = ".comic-chat-write-probe-"


def _probe_writable(path: Path) -> bool:
    """目录是否存在、能否创建并写入一个探针文件（不保证能删除）。"""
    try:
        path.mkdir(parents=True, exist_ok=True)
        probe = path / f"{_PROBE_PREFIX}{os.getpid()}"
        with open(probe, "wb") as fh:
            fh.write(b"ok")
        try:
            probe.unlink()
        except OSError:
            # 某些沙箱 ACL 只禁止删除、不禁止写入；能写就够 Chroma/fastembed 用了。
            pass
        return True
    except OSError:
        return False


def _temp_candidates() -> list[Path]:
    """当前进程实际会拿到的临时目录候选项（只认环境变量，不认 tempfile 的 cwd 回退）。"""
    candidates: list[Path] = []
    for name in ("TMP", "TEMP", "TMPDIR"):
        raw = os.environ.get(name, "").strip()
        if raw:
            candidates.append(Path(raw))
    if not candidates:
        # 三个环境变量都没设时才问 Python；否则不能把它的 cwd 回退当成“系统临时目录可写”。
        try:
            candidates.append(Path(tempfile.gettempdir()))
        except Exception:  # noqa: BLE001 —— 取不到就按“不可写”处理
            pass
    return candidates


def _prepare_temp_dir() -> None:
    candidates = _temp_candidates()
    if any(_probe_writable(path) for path in candidates):
        return
    fallback = DATA_ROOT / "tmp"
    if not _probe_writable(fallback):
        logger.warning("系统临时目录不可写，且无法创建 %s —— 继续启动，可能会失败", fallback)
        return
    for name in ("TMP", "TEMP", "TMPDIR"):
        os.environ[name] = str(fallback)
    tempfile.tempdir = str(fallback)
    logger.warning("系统临时目录不可写，chat 改用项目内目录：%s", fallback)


def _prepare_model_cache() -> None:
    """开发态默认把 fastembed 缓存放到 DATA_ROOT 下（容器里保持 HF_HOME 不变）。"""
    if os.environ.get("FASTEMBED_CACHE_PATH"):
        return
    chat_root = Path(__file__).resolve().parents[2]  # .../chat-service
    if not (chat_root / "pyproject.toml").is_file():
        return  # wheel / 容器：不要覆盖 Dockerfile 预热的 HF_HOME
    cache = DATA_ROOT / "fastembed_cache"
    if _probe_writable(cache):
        os.environ["FASTEMBED_CACHE_PATH"] = str(cache)


def prepare() -> None:
    """幂等地准备临时目录与模型缓存；只应在导入 rag 之前调用一次。"""
    global _PREPARED
    if _PREPARED:
        return
    _PREPARED = True

    if os.name == "nt":
        _prepare_temp_dir()
        _prepare_model_cache()

    # Chroma / huggingface_hub 的匿名遥测：本地开发不需要，也避免额外网络请求。
    os.environ.setdefault("ANONYMIZED_TELEMETRY", "False")
    os.environ.setdefault("HF_HUB_DISABLE_TELEMETRY", "1")
