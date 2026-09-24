"""跨模块边界守卫：断言 api-service 只通过**唯一契约面**依赖采集包。

约定（见 `crawler-service/src/comic_crawler/facade.py`）：

    api-service 只允许 `from comic_crawler.facade import ...`，
    不得 import `comic_crawler` 的任何子模块。

**为什么要有这个测试**：采集侧内部重构（换存储实现、拆 `comic_store`、重排
`scheduling` 的模块）本该对 api 零影响 —— 前提是 api 不穿透到子模块。一旦有人图省事写
`from comic_crawler.storage.mysql import MySQLStorage`，api 就悄悄绑定了采集包的内部
结构，采集侧再动它就得连带改 api。把它变成断言后，这种穿透会立刻红。

本文件是**纯 AST 静态扫描**：不导入任何应用模块，因此**不连库、不需要环境变量**。
"""
from __future__ import annotations

import ast
import unittest
from pathlib import Path

APP_DIR = Path(__file__).resolve().parents[1]

CRAWLER_PKG = "comic_crawler"
FACADE = f"{CRAWLER_PKG}.facade"

# 扫描时跳过的目录（测试自身、构建产物、缓存、虚拟环境、图库）
_SKIP_PARTS = {"tests", "__pycache__", ".venv", "dist", "build", "image_store"}

# 采集包契约面的源码位置（读 `__all__` 用；仅仓库内开发态存在）
_FACADE_PATH = APP_DIR.parent / "crawler-service" / "src" / "comic_crawler" / "facade.py"


def _app_files() -> list[Path]:
    """api-service 下所有业务 .py（跳过测试、构建产物、缓存）。"""
    out: list[Path] = []
    for path in sorted(APP_DIR.rglob("*.py")):
        rel_parts = path.relative_to(APP_DIR).parts
        if any(part in _SKIP_PARTS for part in rel_parts):
            continue
        out.append(path)
    return out


def _crawler_imports(
    source: str, filename: str = "<test>"
) -> list[tuple[int, str, list[str]]]:
    """源码里所有指向采集包的导入 → [(行号, 模块全名, 引入的名字列表)]。

    `from comic_crawler.facade import X` → `(n, "comic_crawler.facade", ["X"])`；
    `from comic_crawler import logctx`   → `(n, "comic_crawler", ["logctx"])`；
    `import comic_crawler.paths`         → `(n, "comic_crawler.paths", [])`。

    相对导入（`level > 0`）不可能指向采集包（api-service 是独立包），忽略。
    """
    tree = ast.parse(source, filename=filename)
    found: list[tuple[int, str, list[str]]] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            mod = node.module or ""
            if node.level == 0 and (mod == CRAWLER_PKG or mod.startswith(CRAWLER_PKG + ".")):
                found.append((node.lineno, mod, [a.name for a in node.names]))
        elif isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name == CRAWLER_PKG or alias.name.startswith(CRAWLER_PKG + "."):
                    found.append((node.lineno, alias.name, []))
    return found


def _boundary_violations(source: str, filename: str = "<test>") -> list[str]:
    """返回该源码里「穿透契约面」的违规描述（空 = 合规）。"""
    out: list[str] = []
    for lineno, mod, _names in _crawler_imports(source, filename):
        if mod != FACADE:
            out.append(f"{filename}:{lineno} → {mod}（只允许 {FACADE}）")
    return out


def _used_symbols(source: str, filename: str = "<test>") -> list[str]:
    """该源码从契约面取用的符号名（`import *` 不计）。"""
    out: list[str] = []
    for _lineno, mod, names in _crawler_imports(source, filename):
        if mod == FACADE:
            out += [n for n in names if n != "*"]
    return out


def _facade_ast() -> ast.Module:
    return ast.parse(_FACADE_PATH.read_text("utf-8"), filename=str(_FACADE_PATH))


def _facade_all() -> list[str]:
    """静态解析 `facade.py` 的 `__all__`（契约清单）。"""
    for node in _facade_ast().body:
        if isinstance(node, ast.Assign):
            if any(isinstance(t, ast.Name) and t.id == "__all__" for t in node.targets):
                return [e.value for e in node.value.elts if isinstance(e, ast.Constant)]
    return []


def _facade_imported_names() -> set[str]:
    """`facade.py` 里通过 import 引入的名字（含 `as` 后的新名；排除 `__future__`）。"""
    names: set[str] = set()
    for node in ast.walk(_facade_ast()):
        if isinstance(node, ast.ImportFrom) and node.module != "__future__":
            for alias in node.names:
                names.add(alias.asname or alias.name)
    return names


class TestCrawlerBoundary(unittest.TestCase):
    """api → 采集包 的依赖面守卫（纯静态，不导入应用模块）。"""

    def test_only_facade_is_imported(self) -> None:
        """api 只能 import 契约面，不得穿透到采集包子模块。"""
        violations: list[str] = []
        for path in _app_files():
            rel = path.relative_to(APP_DIR).as_posix()
            violations += _boundary_violations(path.read_text("utf-8"), rel)
        self.assertEqual(
            violations,
            [],
            "检测到「api 穿透采集包子模块」（应改走契约面 "
            f"`from {FACADE} import ...`）:\n  " + "\n  ".join(violations),
        )

    @unittest.skipUnless(_FACADE_PATH.is_file(), f"未找到采集包契约面：{_FACADE_PATH}")
    def test_used_symbols_are_declared(self) -> None:
        """api 取用的每个符号都必须在契约面 `__all__` 里声明（防隐性契约）。"""
        declared = set(_facade_all())
        used: set[str] = set()
        for path in _app_files():
            used.update(_used_symbols(path.read_text("utf-8")))
        self.assertEqual(
            sorted(used - declared),
            [],
            "以下符号被 api 使用但未在 facade.__all__ 声明（请补进契约清单）：\n  "
            + "\n  ".join(sorted(used - declared)),
        )

    @unittest.skipUnless(_FACADE_PATH.is_file(), f"未找到采集包契约面：{_FACADE_PATH}")
    def test_facade_all_matches_imports(self) -> None:
        """契约面自身要对齐：`__all__` 与 import 进来的名字必须一致（无空转、无漏列）。"""
        declared = set(_facade_all())
        imported = _facade_imported_names()
        self.assertEqual(
            sorted(declared - imported),
            [],
            "facade.__all__ 列了但模块里没导入（空转条目）：\n  "
            + "\n  ".join(sorted(declared - imported)),
        )
        self.assertEqual(
            sorted(imported - declared),
            [],
            "facade.py 导入了但未列入 __all__（对 api 不可见）：\n  "
            + "\n  ".join(sorted(imported - declared)),
        )

    def test_guard_actually_detects_violation(self) -> None:
        """自检：伪造穿透源码，守卫必须报出来（防守卫失效）。"""
        bad = "from comic_crawler.storage.mysql import MySQLStorage\n"
        self.assertTrue(_boundary_violations(bad, "fake.py"))
        bad_bare = "from comic_crawler import logctx\n"
        self.assertTrue(_boundary_violations(bad_bare, "fake.py"))
        good = f"from {FACADE} import MySQLStorage\n"
        self.assertEqual(_boundary_violations(good, "fake.py"), [])
        self.assertEqual(_used_symbols(good, "fake.py"), ["MySQLStorage"])


if __name__ == "__main__":
    unittest.main()
