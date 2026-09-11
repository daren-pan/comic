#!/usr/bin/env bash
# ============================================================
#  One-shot self-check. Run from repo root: ./scripts/check.sh
#
#    1) crawler-service unit tests   (pipeline + adapters + layering guard + inspect paging)
#    2) api-service layering guard   (core -> schemas/serializers -> services -> routers)
#    3) frontend type check          (tsc --noEmit)
#
#  Why: the layering guards only fire if someone actually runs the tests.
#  Wire this into a git hook to enforce it automatically:
#      ln -sf ../../scripts/check.sh .git/hooks/pre-commit
# ============================================================
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"

PY="$ROOT/crawler-service/.venv/Scripts/python.exe"          # Windows venv layout
[ -x "$PY" ] || PY="$ROOT/crawler-service/.venv/bin/python"  # macOS / Linux

echo "-> [1/3] crawler-service unit tests"
(cd "$ROOT/crawler-service" && "$PY" -m unittest discover -s tests)

echo "-> [2/3] api-service layering guard"
(cd "$ROOT/api-service" && "$PY" -m unittest discover -s tests)

echo "-> [3/3] frontend type check (tsc --noEmit)"
(cd "$ROOT/comic-web" && npx tsc --noEmit)

echo "OK  all checks passed"
