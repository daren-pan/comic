"""导出后端 OpenAPI 快照 —— 前端 `npm run gen:api` 生成类型时读它。

用法（从**仓库根**跑）：

    crawler-service/.venv/Scripts/python.exe tools/export_openapi.py

为什么用 in-process 导出（而不是 curl 在跑的服务）：

- **不要求后端在跑** —— `import main` 只做 app 装配（路由注册等），不触发 lifespan、
  不连库，任何环境都能稳定拿到契约快照；
- 只要后端有改动（加了字段 / 改了接口），重跑本脚本 + `npm run gen:api`
  就能把变化传导到前端类型（消除「手抄 types.ts 漂移」的根因）。

产物 `api-service/openapi.json` **提交进仓库**：让前端生成类型不依赖 Python 环境。
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
API_DIR = ROOT / "api-service"
sys.path.insert(0, str(API_DIR))

from main import app  # noqa: E402 —— 必须在 sys.path 引导之后导入

out = API_DIR / "openapi.json"
spec = app.openapi()
out.write_text(json.dumps(spec, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

n_paths = len(spec["paths"])
n_schemas = len(spec.get("components", {}).get("schemas", {}))
print(f"已导出 {out.relative_to(ROOT)}")
print(f"  paths={n_paths}  schemas={n_schemas}  bytes={out.stat().st_size}")
