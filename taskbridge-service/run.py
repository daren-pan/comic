"""启动入口：`python taskbridge-service/run.py`

为什么不直接 `uvicorn taskbridge.main:app`：本模块是**目录即包**（`taskbridge-service/`
下放平铺的模块文件 + 一个 `taskbridge` 包名映射），仓库根不是 Python 包，
这里把本目录塞进 sys.path，让 `taskbridge` 作为普通包被导入，相对导入才成立。
"""

from __future__ import annotations

import pathlib
import sys

MODULE_DIR = pathlib.Path(__file__).resolve().parents[1]
if str(MODULE_DIR) not in sys.path:
    sys.path.insert(0, str(MODULE_DIR))

import uvicorn  # noqa: E402

from taskbridge import config  # noqa: E402

if __name__ == "__main__":
    print(f"[taskbridge] repo={config.REPO_ROOT}")
    print(f"[taskbridge] model={config.OPENCODE_MODEL}  timeout={config.TASK_TIMEOUT}s")
    print(f"[taskbridge] listen={config.HOST}:{config.PORT}")
    uvicorn.run("taskbridge.main:app", host=config.HOST, port=config.PORT, log_level="info")
