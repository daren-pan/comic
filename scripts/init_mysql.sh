#!/usr/bin/env bash
# Init MySQL database "comic" from crawler-service/sql/comic_full_init.sql
# Idempotent: CREATE DATABASE IF NOT EXISTS + DROP TABLE + re-create + insert.
# WARNING: existing comic.* tables in target MySQL will be DROPPED!
# Usage:  init_mysql.sh [mysql-host] [port]
set -e
cd "$(dirname "$0")/.."
HOST="${1:-127.0.0.1}"
PORT="${2:-3307}"

echo "Importing into mysql://$HOST:$PORT ..."
mysql -h"$HOST" -P"$PORT" -uroot -ppassword --default-character-set=utf8mb4 < crawler-service/sql/comic_full_init.sql
echo "Done. comic database ready (8 comics / 31 chapters / 344 pages)."
