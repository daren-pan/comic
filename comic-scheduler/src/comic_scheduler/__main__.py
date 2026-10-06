"""`python -m comic_scheduler` 入口 —— 与控制台脚本 `comic-scheduler` 等价。"""
from __future__ import annotations

from .daemon import main

if __name__ == "__main__":
    raise SystemExit(main())
