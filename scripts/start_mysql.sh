#!/usr/bin/env bash
# MySQL mode: start site on :8000 reading the comic database.
# Requires: MySQL reachable (default 127.0.0.1:3307 root/password, override with COMIC_MYSQL_*)
set -e
cd "$(dirname "$0")/../api-service"

if ! command -v python3 >/dev/null 2>&1 && ! command -v python >/dev/null 2>&1; then
    echo "[ERROR] python not found. Install Python 3.10+ first."
    exit 1
fi
PY=python3; command -v python3 >/dev/null 2>&1 || PY=python

export COMIC_DB_TYPE=mysql
echo "Starting comic site (MySQL mode) on http://127.0.0.1:8000 ..."
exec "$PY" -m uvicorn main:app --host 127.0.0.1 --port 8000
