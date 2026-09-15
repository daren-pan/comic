#!/usr/bin/env bash
# 本地开发用：起站点到 :8000 读 MySQL（**上线走 deploy/ 的 Docker**）
# Start site on :8000 reading the MySQL comic database (唯·存储方案).
# Requires: DB container up (宿主 127.0.0.1:3309; 参数自动读 deploy/.env, override with COMIC_MYSQL_*)
set -e
cd "$(dirname "$0")/../api-service"

if ! command -v python3 >/dev/null 2>&1 && ! command -v python >/dev/null 2>&1; then
    echo "[ERROR] python not found. Install Python 3.10+ first."
    exit 1
fi
PY=python3; command -v python3 >/dev/null 2>&1 || PY=python

echo "Starting comic site (MySQL mode) on http://127.0.0.1:8000 ..."
exec "$PY" -m uvicorn main:app --host 127.0.0.1 --port 8000
