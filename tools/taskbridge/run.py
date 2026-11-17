"""启动入口：`python tools/taskbridge/run.py`

为什么不直接 `uvicorn tools.taskbridge.main:app`：仓库根不是 Python 包（没有 `__init__.py`），
这里把 `tools/` 塞进 sys.path，让 `taskbridge` 作为一个普通包被导入，相对导入才成立。
"""

from __future__ import annotations

import pathlib
import sys

TOOLS_DIR = pathlib.Path(__file__).resolve().parents[1]
if str(TOOLS_DIR) not in sys.path:
    sys.path.insert(0, str(TOOLS_DIR))

import uvicorn  # noqa: E402

from taskbridge import config  # noqa: E402

if __name__ == "__main__":
    print(f"[taskbridge] repo={config.REPO_ROOT}")
    print(f"[taskbridge] model={config.OPENCODE_MODEL}  timeout={config.TASK_TIMEOUT}s")
    print(f"[taskbridge] listen={config.HOST}:{config.PORT}")
    uvicorn.run("taskbridge.main:app", host=config.HOST, port=config.PORT, log_level="info")
