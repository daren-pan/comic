#!/usr/bin/env bash
# 项目知识库统一入口 —— 一条命令 + 参数，覆盖 检索 / 评测 / 建索引 / 自检。
#
# 为什么要这个脚本：CLI 本体是 Python 模块，直接跑要手工设 PYTHONPATH、
# 还得用对解释器（venv）和临时目录（Chroma 的 Rust SQLite 只认系统临时目录）。
# 这些琐事收在这里，日常只记一条命令。
#
# 路径写法照 `scripts/dev.sh` 的 knowledge 段：PYTHONPATH 用**相对路径** + `cd $ROOT`，
# Windows(Git Bash) 用 `;` 分隔、POSIX 用 `:` —— 避开 MSYS 路径转换的坑。
#
# 用法：
#   bash scripts/kb.sh ask "<你的问题>"
#   bash scripts/kb.sh ask "问题A" "问题B" --top-k 5
#   bash scripts/kb.sh search "X-Service-Token" --explain
#   bash scripts/kb.sh eval --mode hybrid --detail
#   bash scripts/kb.sh index --check
set -euo pipefail

here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
root="$(dirname "$here")"

usage() {
  cat <<'EOF'
项目知识库 · 统一入口

  kb.sh ask    <问题> [<问题>...] [--top-k N] [--mode hybrid|vector|lexical]
        直接给答案：路径 / 小节 / 摘要（多个问题一次问完）

  kb.sh search <问题> [--explain] [--top-k N] [--mode ...] [--kind ...] [--module ...]
        排查用：--explain 打分数构成表；不加则输出 JSON

  kb.sh eval   [--mode ...] [--detail] [--json] [--top-k N]
        20 条黄金题：Recall / MRR / nDCG / Top-1
        --detail 逐题列出全部命中（人工核对），--json 供脚本消费

  kb.sh read   <doc_id>          按 doc_id 回读小节全文
  kb.sh index  [--check]         全量重建（约 40 秒）/ 只查是否过期
  kb.sh doctor                   自检：embedding / 分词 / 条数 / 是否过期
  kb.sh stats  [--detail]        索引摘要（JSON）

例：
  bash scripts/kb.sh ask "怎么新增一个爬虫源"
  bash scripts/kb.sh eval --mode vector
  bash scripts/kb.sh search "同源判重键" --explain --top-k 5
EOF
}

if [ $# -eq 0 ]; then usage; exit 0; fi
case "${1:-}" in
  help|-h|--help) usage; exit 0 ;;
esac

PY="$root/crawler-service/.venv/Scripts/python.exe"
[ -x "$PY" ] || PY="$root/crawler-service/.venv/bin/python"
if [ ! -x "$PY" ]; then
  echo "[kb] 找不到项目内的 Python：$PY" >&2
  echo "[kb] 先执行：bash scripts/dev.sh bootstrap knowledge" >&2
  exit 1
fi

# Git Bash 的 /d/x 写给 Windows 原生库（SQLite / fastembed）时要是 D:\x
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

case "$(uname -s)" in
  MINGW*|MSYS*|CYGWIN*) export PYTHONPATH="knowledge-mcp/src;chat-service/src;comic-core/src" ;;
  *)                    export PYTHONPATH="knowledge-mcp/src:chat-service/src:comic-core/src" ;;
esac

cd "$root"
exec "$PY" -m comic_rag_mcp.cli "$@"
