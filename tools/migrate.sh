#!/usr/bin/env bash
# ============================================================
#  统一迁移执行器 —— 只执行"还没跑过"的迁移（记录在 schema_migration 表）
#
#  迁移文件：tools/migrations/NNNN_<snake_case>.sql（按文件名排序执行）
#  执行方式：把 SQL 文件通过 stdin 喂给 **comic-mysql 容器**里的 mysql 客户端
#            （不依赖 Python、不需要挂载、不改 compose）
#
#  用法（在仓库根目录）：
#    bash tools/migrate.sh              # 执行所有未跑过的迁移（结束后自动体检）
#    bash tools/migrate.sh --list       # 只看状态（已执行 / 待执行），不改库
#    bash tools/migrate.sh --dry-run    # 预演：列出会跑哪些，不执行
#    bash tools/migrate.sh --baseline   # 把当前全部迁移标记为"已执行"（不跑）—— 存量库首次接入用
#    bash tools/migrate.sh --mark <名>  # 手动把某个迁移标记为已执行（修复用）
#    bash tools/migrate.sh --check      # 体检：库里的表 vs schema 声明的表（只读）
#    bash tools/migrate.sh -h
#
#  约定（见 tools/README.md）：
#    · 迁移文件**只跑一次**（记录表保证）—— 文件里写最朴素的 SQL 即可，不必做重复保护；
#    · 跑到一半失败 → 不登记 → 修好后重跑（已成功的前半段会报错；人工判断后用 --mark 登记）；
#    · 记录表丢了 / 换库 → 迁移会重跑，届时人工介入（--baseline / --mark）；
#    · 全新库不需要跑迁移（mysql_schema.sql 已建全表）—— 误跑会报错，属预期。
# ============================================================
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
MIG_DIR="$ROOT/tools/migrations"
SCHEMA_FILE="$ROOT/comic-core/sql/mysql_schema.sql"
CONTAINER="${COMIC_MYSQL_CONTAINER:-comic-mysql}"

# 可选：把操作指向另一个库（默认用容器内的 MYSQL_DATABASE，即 comic）—— 演练 / 测试用
DB_ARGS=()
if [ -n "${COMIC_MYSQL_DB:-}" ]; then
  DB_ARGS=(-e "MYSQL_DATABASE=${COMIC_MYSQL_DB}")
fi

MODE="run"
MARK_NAME=""
case "${1:-}" in
  --list)     MODE="list" ;;
  --dry-run)  MODE="dry-run" ;;
  --baseline) MODE="baseline" ;;
  --check)    MODE="check" ;;
  --mark)     MODE="mark"; MARK_NAME="${2:?--mark 后面要跟迁移文件名，如 0010_add_xxx.sql}" ;;
  -h|--help)  awk 'NR==1{next} {sub(/^# ?/,"")} NR>2 && /^=+$/ {print; exit} {print}' "$0"; exit 0 ;;
  "") ;;
  *) echo "!! 未知参数：$1（-h 看用法）" >&2; exit 1 ;;
esac

docker inspect "$CONTAINER" >/dev/null 2>&1 || {
  echo "!! 找不到容器 $CONTAINER —— 先起 mysql：docker compose -f deploy/docker-compose.yml up -d comic-mysql" >&2
  exit 1
}

# ---- 在 mysql 容器内执行（密码从容器自身环境变量取，不进宿主命令行）----
q() {  # q <sql>：查询，制表符分隔、无表头
  docker exec "${DB_ARGS[@]}" "$CONTAINER" sh -c 'MYSQL_PWD="$MYSQL_ROOT_PASSWORD" mysql -uroot "$MYSQL_DATABASE" -N -B -e "$1"' sh "$1"
}
x() {  # x <sql>：执行（不取结果）
  docker exec "${DB_ARGS[@]}" "$CONTAINER" sh -c 'MYSQL_PWD="$MYSQL_ROOT_PASSWORD" mysql -uroot "$MYSQL_DATABASE" -e "$1"' sh "$1"
}
run_file() {  # run_file <sql 文件>：整文件按序执行
  docker exec -i "${DB_ARGS[@]}" "$CONTAINER" sh -c 'MYSQL_PWD="$MYSQL_ROOT_PASSWORD" mysql -uroot "$MYSQL_DATABASE"' < "$1"
}

# ---- 记录表（执行器自己维护，不属于任何迁移）----
x "CREATE TABLE IF NOT EXISTS schema_migration (
     name VARCHAR(128) NOT NULL PRIMARY KEY COMMENT '迁移文件名（NNNN_xxx.sql）',
     applied_at DATETIME NOT NULL COMMENT '执行时间'
   ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='迁移执行记录（tools/migrate.sh 维护）'"

applied() { [ "$(q "SELECT COUNT(*) FROM schema_migration WHERE name = '$1'")" = "1" ]; }

# ---- 体检：库表 vs schema 声明的表（只读）----
do_check() {
  expected="$(grep -o "CREATE TABLE IF NOT EXISTS [a-z_]*" "$SCHEMA_FILE" | sed "s/.* //" | sort)"
  actual="$(q "SHOW TABLES" | sort)"
  missing="$(comm -23 <(printf '%s\n' "$expected") <(printf '%s\n' "$actual") || true)"
  if [ -n "$missing" ]; then
    echo "  !! 缺表：$(printf '%s' "$missing" | tr '\n' ' ')"
    return 1
  fi
  echo "  表齐全（$(printf '%s\n' "$expected" | wc -l | tr -d ' ') 张）✓"
}

if [ "$MODE" = "check" ]; then
  echo "体检：库表 vs schema"
  do_check
  exit $?
fi

# ---- 迁移清单 ----
FILES=("$MIG_DIR"/*.sql)
[ -e "${FILES[0]}" ] || { echo "!! $MIG_DIR 下没有 .sql 迁移文件" >&2; exit 1; }

if [ "$MODE" = "mark" ]; then
  [ -f "$MIG_DIR/$MARK_NAME" ] || { echo "!! 找不到迁移文件：$MARK_NAME" >&2; exit 1; }
  x "INSERT IGNORE INTO schema_migration (name, applied_at) VALUES ('$MARK_NAME', NOW())"
  echo "  已登记：$MARK_NAME"
  exit 0
fi

if [ "$MODE" = "baseline" ]; then
  echo "基线登记（不执行，仅把现有迁移标记为已执行）"
  for f in "${FILES[@]}"; do
    name="$(basename "$f")"
    if applied "$name"; then
      echo "  已登记：$name"
    else
      x "INSERT INTO schema_migration (name, applied_at) VALUES ('$name', NOW())"
      echo "  标记为已执行：$name"
    fi
  done
  exit 0
fi

# ---- 主循环（按文件名 = 编号顺序）----
pending=0
for f in "${FILES[@]}"; do
  name="$(basename "$f")"
  if applied "$name"; then
    if [ "$MODE" = "run" ]; then
      echo "  跳过（已执行）：$name"
    fi
    continue
  fi
  pending=$((pending + 1))
  case "$MODE" in
    list|dry-run)
      echo "  待执行：$name"
      ;;
    run)
      echo "  执行：$name"
      if ! run_file "$f"; then
        echo "  !! 失败：$name —— 未登记；修复后重跑，或确认已生效后用 --mark $name 手动登记" >&2
        exit 1
      fi
      x "INSERT INTO schema_migration (name, applied_at) VALUES ('$name', NOW())"
      echo "  ✓ 完成：$name"
      ;;
  esac
done

case "$MODE" in
  list)
    if [ "$pending" = "0" ]; then echo "  （没有待执行的迁移）"; fi
    ;;
  dry-run)
    echo "  [dry-run] 共 $pending 个待执行，未改动数据库"
    ;;
  run)
    if [ "$pending" = "0" ]; then
      echo "  没有待执行的迁移（全部已执行过）"
    else
      echo "  ✓ 共执行 $pending 个迁移"
    fi
    echo "体检："
    do_check
    ;;
esac
