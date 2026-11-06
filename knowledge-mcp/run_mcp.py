"""MCP 启动器：给 DSH / Claude Desktop / Cursor 直接指向 python.exe + 本文件。

为什么需要它：DSH 的 MCP 客户端对 `env` 字段的支持因版本而异；把路径和环境变量
放在 Python 启动器里，配置只需要 `command` + `args`，不依赖客户端是否支持 env。

本文件不做业务，只做三件事：
1. 把 `knowledge-mcp/src`、`chat-service/src`、`comic-core/src` 放进 sys.path；
2. 设置项目内临时目录 / 模型缓存（DSH 受限会话必需）；
3. 调 `comic_rag_mcp.__main__.main()`（stdio MCP）。
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
for rel in ("knowledge-mcp/src", "chat-service/src", "comic-core/src"):
    path = str(ROOT / rel)
    if path not in sys.path:
        sys.path.insert(0, path)

# 只在调用方没显式设置时兜底；显式环境变量优先。
os.environ.setdefault("COMIC_RAG_ROOT", str(ROOT))
os.environ.setdefault("COMIC_RAG_INDEX_DIR", str(ROOT / "crawler-service" / "data" / "project_rag"))

# ⚠️ TMP/TEMP/TMPDIR 必须**三个都覆盖**，不能 setdefault：Windows 默认的 TEMP 可能
# 指向工作区外不可写的 DSH 目录，只改 TMP 不足以让 Chroma 的 Rust 绑定避开它。
_TMP = str(ROOT / "crawler-service" / "data" / "tmp")
os.environ["TMP"] = _TMP
os.environ["TEMP"] = _TMP
os.environ["TMPDIR"] = _TMP
os.environ.setdefault(
    "FASTEMBED_CACHE_PATH", str(ROOT / "crawler-service" / "data" / "fastembed_cache")
)
os.environ.setdefault("HF_HUB_DISABLE_TELEMETRY", "1")
os.environ.setdefault("ANONYMIZED_TELEMETRY", "False")

from comic_rag_mcp.__main__ import main  # noqa: E402

if __name__ == "__main__":
    main()
