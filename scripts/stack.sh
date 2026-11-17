#!/usr/bin/env bash
# 两套栈的统一编排入口（Linux / 服务器）
#   Comic 栈 = deploy/docker-compose.yml           项目名 comic
#   Dify 栈  = ../dify/docker/docker-compose.yaml  项目名 docker
#
# 用法：
#   bash scripts/stack.sh status
#   bash scripts/stack.sh up    [comic|dify|all]
#   bash scripts/stack.sh down  [comic|dify|all]
#   bash scripts/stack.sh restart [comic|dify|all]
#   bash scripts/stack.sh logs <服务名> [行数]
#
# 设计原则：不改任何一方的 compose 文件，只做统一调用与状态聚合。
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
COMIC_FILE="$REPO_ROOT/deploy/docker-compose.yml"
DIFY_FILE="$(dirname "$REPO_ROOT")/dify/docker/docker-compose.yaml"

ACTION="${1:-status}"
TARGET="${2:-all}"
EXTRA="${3:-}"

stack_file() { case "$1" in comic) echo "$COMIC_FILE" ;; dify) echo "$DIFY_FILE" ;; esac; }
stack_project() { case "$1" in comic) echo comic ;; dify) echo docker ;; esac; }

show_status() {
  echo
  for s in comic dify; do
    f="$(stack_file "$s")"; p="$(stack_project "$s")"
    echo "== $s ($(basename "$f"), project=$p)"
    if [ ! -f "$f" ]; then echo "   文件不存在"; continue; fi
    docker ps -a --filter "label=com.docker.compose.project=$p" \
      --format '   {{.Names}}\t{{.Status}}' || true
  done
  echo
  echo "== 宿主端口 =="
  for port in 80 85 86 3000 6099 5300 5401 8000 8020 3309; do
    if ss -lnt 2>/dev/null | grep -q ":$port "; then echo "   $port LISTEN"; else echo "   $port -"; fi
  done
}

case "$ACTION" in
  status|ps) show_status ;;
  logs)
    [ -n "$TARGET" ] && [ "$TARGET" != "all" ] || { echo "logs 需要指定服务名"; exit 1; }
    docker logs --tail "${EXTRA:-100}" -f "$TARGET" ;;
  up|down|restart)
    targets=("$TARGET")
    [ "$TARGET" = "all" ] && targets=(comic dify)
    for t in "${targets[@]}"; do
      f="$(stack_file "$t")"; p="$(stack_project "$t")"
      [ -n "${f:-}" ] || { echo "未知目标：$t"; exit 1; }
      echo "== $ACTION $t"
      docker compose -f "$f" -p "$p" "$ACTION" -d
    done
    show_status ;;
  *) echo "用法: $0 {status|up|down|restart|logs} [comic|dify|all] [行数]"; exit 1 ;;
esac
