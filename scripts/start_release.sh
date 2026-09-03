#!/usr/bin/env bash
# Release mode (SQLite, no MySQL needed): start site on :8000
# Serves comic-deploy (comic_crawler + dist + comic_demo.db created by cli run)
# NOTE: repo ships no data file - run cli run first to populate comic_demo.db
set -e
cd "$(dirname "$0")/../comic-deploy"

if ! command -v python3 >/dev/null 2>&1 && ! command -v python >/dev/null 2>&1; then
    echo "[ERROR] python not found. Install Python 3.10+ first."
    exit 1
fi
PY=python3; command -v python3 >/dev/null 2>&1 || PY=python

echo "Starting comic site (SQLite mode) on http://127.0.0.1:8000 ..."
exec "$PY" -m uvicorn main:app --host 127.0.0.1 --port 8000
