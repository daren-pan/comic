#!/usr/bin/env bash
# 知识库调试界面（本地用，前端 Vue + Vite，后端 FastAPI）。
#
#   bash scripts/kb-ui.sh                # 默认 8899(后端) / 5175(前端)
#   KB_UI_PORT=9000 bash scripts/kb-ui.sh
#
# 会同时起两个进程：
#   后端  python knowledge-mcp/devui.py      → http://127.0.0.1:8899（API + /docs）
#   前端  npm run dev (knowledge-mcp/devui-web) → http://127.0.0.1:5175（界面）
# 退出脚本（Ctrl+C）时会把后端一起收掉。
#
# ⚠️ 只绑 127.0.0.1，无鉴权，是本地调试工具，不要改成对外监听。
set -euo pipefail

here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
root="$(dirname "$here")"
web="$root/knowledge-mcp/devui-web"

PY="$root/crawler-service/.venv/Scripts/python.exe"
[ -x "$PY" ] || PY="$root/crawler-service/.venv/bin/python"
if [ ! -x "$PY" ]; then
  echo "[kb-ui] 找不到项目内的 Python：$PY" >&2
  echo "[kb-ui] 先执行：bash scripts/dev.sh bootstrap knowledge" >&2
  exit 1
fi

if [ ! -d "$web/node_modules" ]; then
  echo "[kb-ui] 前端依赖没装。先执行：" >&2
  echo "  cd knowledge-mcp/devui-web && npm install --registry=https://registry.npmmirror.com" >&2
  echo "[kb-ui] （也可以直接复用 comic-web 的 node_modules：从 devui-web 目录执行" >&2
  echo "          cmd /c \"mklink /J node_modules ..\\\\..\\\\comic-web\\\\node_modules\"）" >&2
  exit 1
fi

winpath() {
  if command -v cygpath >/dev/null 2>&1; then cygpath -w "$1"; else printf '%s' "$1"; fi
}

tmp="$root/crawler-service/data/tmp"
cache="$root/crawler-service/data/fastembed_cache"
index="$root/crawler-service/data/project_rag"
mkdir -p "$tmp" "$cache" "$index" 2>/dev/null || true

export TMP="$(winpath "$tmp")"
export TEMP="$TMP"
export TMPDIR="$TMP"
export FASTEMBED_CACHE_PATH="$(winpath "$cache")"
export COMIC_RAG_ROOT="$(winpath "$root")"
export COMIC_RAG_INDEX_DIR="$(winpath "$index")"
export PYTHONUTF8=1
export PYTHONIOENCODING=utf-8
export KB_UI_PORT="${KB_UI_PORT:-8899}"

case "$(uname -s)" in
  MINGW*|MSYS*|CYGWIN*) export PYTHONPATH="knowledge-mcp/src;chat-service/src;comic-core/src" ;;
  *)                    export PYTHONPATH="knowledge-mcp/src:chat-service/src:comic-core/src" ;;
esac

cd "$root/knowledge-mcp"
"$PY" devui.py &
BACKEND_PID=$!
cleanup() {
  echo ""
  echo "[kb-ui] 收尾：停止后端（pid $BACKEND_PID）"
  kill "$BACKEND_PID" 2>/dev/null || true
}
trap cleanup EXIT INT TERM

echo "[kb-ui] 后端 → http://127.0.0.1:${KB_UI_PORT}  （API 文档 /docs）"
echo "[kb-ui] 界面 → http://127.0.0.1:5175"
cd "$web"
npm run dev
