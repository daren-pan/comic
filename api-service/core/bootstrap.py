"""进程启动引导：把**公共内核**与**采集层**的源码目录注入 `sys.path`（**导入即执行，幂等**）。

⚠️ **必须在任何 `import comic_core` / `import comic_crawler` 之前导入本模块。**
开发态直跑时这两个包都不在 site-packages 里，只能靠这里把它们的 `src` 目录加进
模块搜索路径；wheel 态（容器）它们已由 pip 装进 site-packages，下面几个候选目录
都不存在、循环自然跳过。

**为什么与 `core.config` 分开**（2026-09-24 调整）：改 `sys.path` 是**导入副作用**，
而 config 只该是常量。两者混在一起时，任何「只想要一个路径常量」的调用方都会被迫
触发一次路径注入 —— 而且「必须先 import config 才能 import comic_core」这条隐式
顺序依赖只能靠 `# noqa` 注释口口相传。拆开后，副作用只在这一个模块里、名字就说清了
它的用途：需要共享包的地方，先 `from core import bootstrap`。
"""
from __future__ import annotations

import sys
from pathlib import Path

from core import config

# 各共享包的搜索路径候选（下表为「可导入该包的父目录」）：
#   1) 开发态   <repo>/comic-core/src        （comic_core）
#   2) 开发态   <repo>/crawler-service/src   （comic_crawler）
#   3) 打包态   <bundle>                     （包目录与 main.py 同级）
#   4) 打包态   <bundle>/src                 （与开发态同构，让图库根解析一致）
#   5) wheel 态 无需处理 —— 包作为依赖被 pip 装进 site-packages 直接可导入，
#               上面几个候选目录都不存在时循环自然跳过（见 deploy/ 的镜像构建）
CORE_SRC = config.ROOT / "comic-core" / "src"
CRAWLER_SRC = config.ROOT / "crawler-service" / "src"

_PKG_PARENTS: tuple[Path, ...] = (CORE_SRC, CRAWLER_SRC, config.APP_DIR, config.APP_DIR / "src")
_SHARED_PKGS: tuple[str, ...] = ("comic_core", "comic_crawler")


def ensure_packages_on_path() -> None:
    """把共享包的源码目录注入 `sys.path`（幂等：已在路径上就不重复插入）。"""
    for pkg_parent in _PKG_PARENTS:
        for pkg in _SHARED_PKGS:
            if (pkg_parent / pkg).is_dir() and str(pkg_parent) not in sys.path:
                sys.path.insert(0, str(pkg_parent))


ensure_packages_on_path()
