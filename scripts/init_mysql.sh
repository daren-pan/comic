#!/usr/bin/env bash
# 把 crawler-service/sql/mysql_schema.sql 导进目标 MySQL（建库 + 建表）。
#
# 幂等：CREATE DATABASE IF NOT EXISTS + 建表全是 CREATE TABLE IF NOT EXISTS，
# 且 schema 里**没有任何 DROP** —— 所以**不会清空已有数据**，任何时候重跑都安全。
#
# ⚠️ 通常**不需要**跑这个脚本：本项目独占的 comic-mysql 容器在数据卷首次初始化时会自动执行
#    建库脚本（10 张表直接建好）。只有「要连外部 MySQL」（不推荐，会与别的系统共库）才手工建。
#
# 口令来源（按序）：环境变量 COMIC_MYSQL_PASSWORD → 仓库根 deploy/.env
#                  （取 COMIC_MYSQL_PASSWORD，回落到 MYSQL_ROOT_PASSWORD）
# Usage:  init_mysql.sh [mysql-host] [port]
set -e
cd "$(dirname "$0")/.."

HOST="${1:-${COMIC_MYSQL_HOST:-127.0.0.1}}"
PORT="${2:-${COMIC_MYSQL_PORT:-${MYSQL_HOST_PORT:-3309}}}"
DB="${COMIC_MYSQL_DB:-comic}"

PW="${COMIC_MYSQL_PASSWORD:-}"
if [ -z "$PW" ] && [ -f deploy/.env ]; then
    PW=$(grep -E '^(COMIC_MYSQL_PASSWORD|MYSQL_ROOT_PASSWORD)=' deploy/.env | tail -1 | cut -d= -f2-)
fi
if [ -z "$PW" ]; then
    echo "[ERROR] 没找到数据库口令。请设 COMIC_MYSQL_PASSWORD，或先："
    echo "          cp deploy/.env.example deploy/.env    # 然后填 MYSQL_ROOT_PASSWORD"
    exit 1
fi

echo "Importing schema into mysql://$HOST:$PORT/$DB ..."
# schema 是纯 DDL、**不含 CREATE DATABASE** —— 库不存在时会直接报 ERROR 1049，故先建库
MYSQL_PWD="$PW" mysql -h"$HOST" -P"$PORT" -uroot \
    -e "CREATE DATABASE IF NOT EXISTS \`$DB\` DEFAULT CHARACTER SET utf8mb4 COLLATE utf8mb4_general_ci"
MYSQL_PWD="$PW" mysql -h"$HOST" -P"$PORT" -uroot --default-character-set=utf8mb4 "$DB" \
    < crawler-service/sql/mysql_schema.sql
echo "Done. $DB 建库建表完成（幂等，未删除任何已有数据）。"
