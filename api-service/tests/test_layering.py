"""分层守卫：断言 api-service 的依赖方向不被破坏。

约定（对应工程原则「分层清楚、单职责」）：

| 层 | 模块 | 允许导入 |
|---|---|---|
| L0 基础设施 | `core.*`（config/db/security/responses） | 仅标准库 / 三方 / **core 自身**（自洽地基） |
| L1 契约与序列化 | `schemas` `serializers` | L0 |
| L2 业务动作 | `services.*`（images/tasks/sources） | L0 · L1 |
| L3 HTTP 接口 | `routers.*`（public/auth/users/admin） | L0 · L1 · L2 |

`main.py` 是**装配入口**（建 app → include_router → 托管 dist），允许依赖任意层，不参与断言。

**为什么要有这个测试**：分层靠人自觉一定会退化成"随手 import"。把它变成断言后，
一旦有人在 `core` 里 import `services`（或 `services` 反向 import `routers`），测试立刻红。

本文件是**纯 AST 静态扫描**：不导入任何应用模块，因此**不连库、不需要环境变量**。
"""
from __future__ import annotations

import ast
import unittest
from pathlib import Path

APP_DIR = Path(__file__).resolve().parents[1]

# 层号越小越"底层/通用"；未列出的模块视为未归类（测试失败，提示补录）
_LAYER_PREFIXES: list[tuple[int, tuple[str, ...]]] = [
    (0, ("core",)),
    (1, ("schemas", "serializers")),
    (2, ("services",)),
    (3, ("routers",)),
]

# 装配入口：允许依赖任意层
_EXEMPT = {"main"}

# 扫描时跳过的目录（测试自身、缓存）
_SKIP_PARTS = {"tests", "__pycache__", ".venv", "dist", "build", "image_store"}


def _module_of(path: Path) -> tuple[str, bool]:
    """文件 → (模块全名, 是否包 __init__)。"""
    rel = path.relative_to(APP_DIR).with_suffix("")
    parts = list(rel.parts)
    is_pkg = parts[-1] == "__init__"
    if is_pkg:
        parts.pop()
    return ".".join(parts), is_pkg


def _layer_of(module: str) -> int | None:
    """按最长前缀匹配层号；None = 未归类。"""
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
    """该文件里所有指向**应用内模块**的导入 → [(行号, 模块全名)]。"""
    mod_name, is_pkg = _module_of(path)
    return _imports_from_source(path.read_text("utf-8"), mod_name, is_pkg, str(path))


def _imports_from_source(
    source: str, mod_name: str, is_pkg: bool, filename: str = "<test>"
) -> list[tuple[int, str]]:
    tree = ast.parse(source, filename=filename)
    found: list[tuple[int, str]] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            if node.level == 0:
                if node.module:
                    found.append((node.lineno, node.module))
                continue
            if node.module:
                found.append((node.lineno, _resolve(mod_name, is_pkg, node.level, node.module)))
            else:  # from . import (a, b) → 每个名字都是子模块
                for alias in node.names:
                    found.append((node.lineno, _resolve(mod_name, is_pkg, node.level, alias.name)))
        elif isinstance(node, ast.Import):
            for alias in node.names:
                found.append((node.lineno, alias.name))
    return found


def _violations(source: str, mod_name: str, is_pkg: bool, filename: str = "<test>") -> list[str]:
    """返回该源码文件里「向上依赖」的违规描述（空 = 合规）。"""
    own = _layer_of(mod_name)
    if own is None:
        return []
    out: list[str] = []
    for lineno, target in _imports_from_source(source, mod_name, is_pkg, filename):
        if target in _EXEMPT:
            continue
        dep = _layer_of(target)
        if dep is None:
            continue  # 标准库 / 三方 / 采集器包（comic_crawler）
        if dep > own:
            out.append(f"{mod_name} (L{own}) → {target} (L{dep})  {filename}:{lineno}")
    return out


def _app_files() -> list[Path]:
    out: list[Path] = []
    for path in sorted(APP_DIR.rglob("*.py")):
        rel_parts = path.relative_to(APP_DIR).parts
        if any(part in _SKIP_PARTS for part in rel_parts):
            continue
        out.append(path)
    return out


class TestLayering(unittest.TestCase):
    """依赖方向守卫（纯静态，不导入应用模块）。"""

    def test_all_modules_are_classified(self) -> None:
        """每个模块都要能归到某一层，否则说明新模块没想清楚定位。"""
        unclassified: list[str] = []
        for path in _app_files():
            mod, _ = _module_of(path)
            if mod in _EXEMPT:
                continue
            if _layer_of(mod) is None:
                unclassified.append(mod)
        self.assertEqual(
            unclassified,
            [],
            "以下模块未归入任何层，请在 tests/test_layering.py 的 _LAYER_PREFIXES 中补录：\n  "
            + "\n  ".join(unclassified),
        )

    def test_no_upward_dependency(self) -> None:
        """低层不得依赖高层：目标层号必须 <= 当前层号。"""
        violations: list[str] = []
        for path in _app_files():
            mod, is_pkg = _module_of(path)
            if mod in _EXEMPT:
                continue
            if _layer_of(mod) is None:
                continue  # 由上一个用例报告
            violations += _violations(path.read_text("utf-8"), mod, is_pkg, path.name)
        self.assertEqual(
            violations,
            [],
            "检测到「低层依赖高层」的分层违规：\n  " + "\n  ".join(violations),
        )

    def test_core_is_self_contained(self) -> None:
        """L0（core）只能依赖自己：core 内互相引用可以，但**不得引用任何上层**。

        （`core.db → core.config`、`core.security → core.db` 这类同层组合是正常的；
        core 作为"地基"必须是自洽的，这样才能被任何层安全复用而不引入环。）
        """
        offenders: list[str] = []
        for path in _app_files():
            mod, _ = _module_of(path)
            if _layer_of(mod) != 0:
                continue
            for lineno, target in _internal_imports(path):
                if target in _EXEMPT:
                    continue
                dep = _layer_of(target)
                if dep is None:
                    continue  # 标准库 / 三方 / 采集器包
                if dep != 0:
                    offenders.append(f"{mod} → {target} (L{dep})  {path.name}:{lineno}")
        self.assertEqual(
            offenders,
            [],
            "L0（core）不得引用上层模块：\n  " + "\n  ".join(offenders),
        )

    def test_guard_actually_detects_violation(self) -> None:
        """自检：伪造一条「core 依赖 routers」的源码，守卫必须报出来（防守卫失效）。"""
        bad = "from routers import public\n"
        self.assertTrue(_violations(bad, "core.db", False, "fake.py"))
        good = "from core.db import db\n"
        self.assertEqual(_violations(good, "routers.public", False, "fake.py"), [])


if __name__ == "__main__":
    unittest.main()
