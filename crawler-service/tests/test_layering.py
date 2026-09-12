"""分层守卫：断言 `comic_crawler` 的依赖方向不被破坏。

约定（见包 docstring）：**通用在外，扩展在里；依赖只能由内向外。**

| 层 | 模块 | 允许导入 |
|---|---|---|
| L0 通用内核 | `models` `config` `http` `fingerprint` `paths` | 仅标准库/三方 |
| L1 契约 | `sources.base` `sources.registry` `storage.base` | L0 |
| L2 实现 | `sources.<源名>` `storage.mysql.*` `images.*` | L0·L1·同层 |
| L3 编排 | `scheduling.*` | L0·L1·L2·同层 |

`cli.py` 是入口，允许依赖任意层（不参与断言）。

**为什么要这个测试**：分层靠人自觉一定会退化成"随手 import"。把它变成断言后，
一旦有人让 `models` 反向依赖 `storage`（或契约层 import 实现层），测试立刻红。
新增模块时若不在下表，测试会提示未归类 —— 这正是提醒你"想清楚它属于哪一层"。
"""
from __future__ import annotations

import ast
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

PKG_DIR = Path(__file__).resolve().parents[1] / "src" / "comic_crawler"
PKG_NAME = "comic_crawler"

# 层号越小越"外层/通用"；未列出的模块视为未归类（测试失败，提示补录）
_LAYER_PREFIXES: list[tuple[int, tuple[str, ...]]] = [
    (0, (
        f"{PKG_NAME}.models",
        f"{PKG_NAME}.config",
        f"{PKG_NAME}.http",
        f"{PKG_NAME}.fingerprint",
        f"{PKG_NAME}.paths",
        f"{PKG_NAME}.taxonomy",
    )),
    (1, (
        f"{PKG_NAME}.sources.base",
        f"{PKG_NAME}.sources.registry",
        f"{PKG_NAME}.storage.base",
    )),
    (2, (
        f"{PKG_NAME}.sources",
        f"{PKG_NAME}.storage.mysql",
        f"{PKG_NAME}.images",
        f"{PKG_NAME}.storage",
    )),
    (3, (
        f"{PKG_NAME}.scheduling",
    )),
]

# 入口与包根：允许依赖任意层
_EXEMPT = {f"{PKG_NAME}.cli", PKG_NAME}


def _module_name(path: Path) -> tuple[str, bool]:
    """文件 → (模块全名, 是否包 __init__)。"""
    rel = path.relative_to(PKG_DIR.parent).with_suffix("")
    parts = list(rel.parts)
    is_pkg = parts[-1] == "__init__"
    if is_pkg:
        parts.pop()
    return ".".join(parts), is_pkg


def _layer_of(module: str) -> int | None:
    """按最长前缀匹配层号；返回 None 表示未归类。"""
    best: tuple[int, int] | None = None  # (前缀长度, 层号)
    for layer, prefixes in _LAYER_PREFIXES:
        for pref in prefixes:
            if module == pref or module.startswith(pref + "."):
                if best is None or len(pref) > best[0]:
                    best = (len(pref), layer)
    return best[1] if best else None


def _resolve(mod_name: str, is_pkg: bool, level: int, target: str | None) -> str:
    """解析相对导入为模块全名（level=1 表示当前包）。"""
    parts = mod_name.split(".")
    if not is_pkg:
        parts = parts[:-1]
    base = parts[: len(parts) - (level - 1)]
    if target:
        base = base + target.split(".")
    return ".".join(base)


def _internal_imports(path: Path) -> list[tuple[int, str]]:
    """该文件里所有指向 comic_crawler 内部的导入 → [(行号, 模块全名)]。"""
    mod_name, is_pkg = _module_name(path)
    tree = ast.parse(path.read_text("utf-8"), filename=str(path))
    found: list[tuple[int, str]] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            if node.level == 0:
                if node.module and node.module.startswith(PKG_NAME):
                    found.append((node.lineno, node.module))
                continue
            if node.module:
                target = _resolve(mod_name, is_pkg, node.level, node.module)
                if target.startswith(PKG_NAME):
                    found.append((node.lineno, target))
            else:  # from . import (a, b)  → 每个名字都是子模块
                for alias in node.names:
                    target = _resolve(mod_name, is_pkg, node.level, alias.name)
                    if target.startswith(PKG_NAME):
                        found.append((node.lineno, target))
        elif isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name.startswith(PKG_NAME):
                    found.append((node.lineno, alias.name))
    return found


def _python_files() -> list[Path]:
    return [p for p in sorted(PKG_DIR.rglob("*.py")) if "__pycache__" not in p.parts]


class TestLayering(unittest.TestCase):
    """依赖方向守卫。"""

    def test_all_modules_are_classified(self) -> None:
        """每个模块都要能归到某一层，否则说明新模块没想清楚定位。"""
        unclassified: list[str] = []
        for path in _python_files():
            mod, _ = _module_name(path)
            if mod in _EXEMPT:
                continue
            if _layer_of(mod) is None:
                unclassified.append(mod)
        self.assertEqual(
            unclassified, [],
            "以下模块未归入任何层，请在 tests/test_layering.py 的 _LAYER_PREFIXES 中补录：\n  "
            + "\n  ".join(unclassified),
        )

    def test_no_inward_to_outward_violation(self) -> None:
        """外层不得依赖里层：目标层号必须 <= 当前层号。"""
        violations: list[str] = []
        for path in _python_files():
            mod, _ = _module_name(path)
            if mod in _EXEMPT:
                continue
            own = _layer_of(mod)
            if own is None:
                continue  # 由上一个用例报告
            for lineno, target in _internal_imports(path):
                if target in _EXEMPT:
                    continue
                dep = _layer_of(target)
                if dep is None:
                    continue
                if dep > own:
                    violations.append(
                        f"{mod} (L{own}) → {target} (L{dep})  {path.name}:{lineno}"
                    )
        self.assertEqual(
            violations, [],
            "检测到「外层依赖里层」的分层违规：\n  " + "\n  ".join(violations),
        )

    def test_contracts_define_expected_abcs(self) -> None:
        """契约层必须真的定义抽象基类（避免契约层被搬空）。"""
        from comic_crawler.sources.base import CrawlerAdapter
        from comic_crawler.storage.base import Storage, UserStore

        self.assertTrue(isinstance(CrawlerAdapter, type))
        self.assertTrue(isinstance(Storage, type))
        self.assertTrue(isinstance(UserStore, type))

    def test_generic_kernel_has_no_internal_deps(self) -> None:
        """L0 通用内核应保持零内部依赖（可被任何层安全复用）。"""
        offenders: list[str] = []
        for path in _python_files():
            mod, _ = _module_name(path)
            if _layer_of(mod) != 0:
                continue
            for lineno, target in _internal_imports(path):
                offenders.append(f"{mod} → {target}  {path.name}:{lineno}")
        self.assertEqual(
            offenders, [],
            "L0 通用内核不应依赖包内其他模块：\n  " + "\n  ".join(offenders),
        )


if __name__ == "__main__":
    unittest.main()
