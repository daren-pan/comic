#!/usr/bin/env bash
# ============================================================
#  One-shot self-check. Run from repo root: ./scripts/check.sh
#
#    1) crawler-service 单测      (pipeline + adapters + 分层守卫 + 状态归一)
#    2) api-service 单测          (core -> schemas_out/serializers -> services -> routers + 响应契约)
#    3) frontend lint             (ESLint：禁裸 alert / localStorage / uni.request)
#    4) frontend 单测             (vitest：路由映射表 + 季节 + 分页状态机 + 约定守卫)
#    5) frontend 类型检查         (tsc --noEmit)
#
#  注：`tsc` 不认 .vue —— 第 5 步只查 .ts（composables / utils / api / stores / types）。
#      .vue 的模板类型要 vue-tsc，暂未纳入；别小看这步：纳入当天就抓到
#      `stores/message.ts` 一个真实缺字段错误（`params`/`minRole`）。
#
#  Why: 这些守卫只有在**真的有人跑**时才生效。
#  Wire this into a git hook to enforce it automatically:
#      ln -sf ../../scripts/check.sh .git/hooks/pre-commit
# ============================================================
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"

PY="$ROOT/crawler-service/.venv/Scripts/python.exe"          # Windows venv layout
[ -x "$PY" ] || PY="$ROOT/crawler-service/.venv/bin/python"  # macOS / Linux

echo "-> [1/5] crawler-service unit tests + 分层守卫"
# ⚠️ `PYTHONPATH` 不能省：`comic_core` / `comic_crawler` 两个本地包**并未安装进 venv**
# （site-packages 里没有任何 comic 相关文件或 .pth），只靠源码路径导入。
# 缺了它，测试模块会在 import 阶段就失败 —— 实测 21 个 ImportError
# （表现为 `unittest.loader._FailedTest`，看起来像"测试挂了"，其实是环境没配好）。
(cd "$ROOT/crawler-service" && PYTHONPATH="src;../comic-core/src" "$PY" -m unittest discover -s tests)

echo "-> [2/5] api-service unit tests + 分层守卫"
(cd "$ROOT/api-service" && "$PY" -m unittest discover -s tests)

echo "-> [3/5] frontend lint (ESLint：禁 alert / localStorage / uni.request)"
(cd "$ROOT/comic-front" && npm run lint)

echo "-> [4/5] frontend unit tests (vitest：路由映射 + 季节 + 分页状态机 + 约定守卫)"
(cd "$ROOT/comic-front" && npm test)

echo "-> [5/5] frontend typecheck (tsc --noEmit：.ts 类型)"
(cd "$ROOT/comic-front" && npm run typecheck)

echo "OK  all checks passed"
