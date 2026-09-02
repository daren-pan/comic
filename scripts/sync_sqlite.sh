#!/usr/bin/env bash
# Refresh the two offline SQLite data files from MySQL comic db
# (requires pymysql: pip install -r crawler-service/requirements.txt)
set -e
cd "$(dirname "$0")/.."
python tools/sync_mysql_to_sqlite.py
echo "Done. crawler-service/comic_demo.db and comic-deploy/comic_demo.db refreshed."
