#!/usr/bin/env bash
# ============================================================
#  Package a deployable bundle (generated on demand; NOT committed).
#
#  Output layout <out>/ (default: build/deploy, override via $1):
#    main.py  core/  routers/  services/  schemas.py  serializers.py   <- HTTP layer (api-service)
#    src/comic_core/                                                    <- shared kernel
#    src/comic_crawler/                                                 <- crawler package
#    dist/                                                              <- frontend build output
#    sql/mysql_schema.sql                                               <- schema bootstrap
#    requirements.txt                                                   <- core + crawler + api deps (merged)
#    README-DEPLOY.md
#
#  ⚠️ 两个包都放 `src/` 下、且**保持和开发树一样的形状**（`src/comic_core/`、`src/comic_crawler/`）——
#     这样 data 目录仍解析到 <bundle>/data/（见 comic-core/src/comic_core/paths.py 的推导）。
#     注意别和上面 api 层的 `core/` 目录搞混：那是 api-service 的 HTTP 分层包，与 comic_core 无关。
#
#  Usage: ./scripts/package.sh [output-dir]
#
#  Refresh policy: **纯覆盖，本脚本不做任何删除**。
#  输出目录往往就是运行目录（运行时数据 data/：图库 image_store/、源开关 source_state.json、
#  现场放的 .env 都住在里面），删除有误伤风险，也让它能在任何权限下重跑。
#  代价："上一版有、这一版没有"的文件会留在输出目录里 —— 脚本末尾会做**遗留检查**
#  并把它们列出来（只报告、不删除），重构改名/挪位置后尤其要看一眼。
# ============================================================
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
OUT="${1:-$ROOT/build/deploy}"

mkdir -p "$OUT/src" "$OUT/sql"

# 复制用 tar 而不是 cp -r：**在复制阶段就排除** __pycache__ / *.pyc，
# 因此不需要"事后扫描删除"，全程无删除动作（脚本可在任何权限下重跑）。
copy_tree() {  # copy_tree <源根目录> <目标目录> <要复制的相对路径...>
  local src="$1" dest="$2"
  shift 2
  ( cd "$src" && tar -cf - --exclude='__pycache__' --exclude='*.pyc' "$@" ) \
    | ( cd "$dest" && tar -xf - )
}

echo "-> copy HTTP layer (api-service)"
copy_tree "$ROOT/api-service" "$OUT" main.py schemas.py serializers.py core routers services

echo "-> copy shared kernel -> src/comic_core"
copy_tree "$ROOT/comic-core/src" "$OUT/src" comic_core

echo "-> copy crawler package -> src/comic_crawler"
copy_tree "$ROOT/crawler-service/src" "$OUT/src" comic_crawler

echo "-> merge requirements (core + crawler + api, dedup)"
sort -u "$ROOT/comic-core/requirements.txt" \
        "$ROOT/crawler-service/requirements.txt" \
        "$ROOT/api-service/requirements.txt" > "$OUT/requirements.txt"

echo "-> copy schema"
cp "$ROOT/comic-core/sql/mysql_schema.sql" "$OUT/sql/"

if [ -d "$ROOT/comic-web/dist" ]; then
  echo "-> copy frontend dist/"
  # 注意：必须用「内容合并」而不是 cp -r "$SRC" "$OUT/dist" ——
  # 目标目录已存在时 cp -r 会把源目录**拷进去**（变成 dist/dist/…），覆盖式重跑就会多套一层。
  mkdir -p "$OUT/dist"
  ( cd "$ROOT/comic-web/dist" && tar -cf - . ) | ( cd "$OUT/dist" && tar -xf - )
else
  echo "!! comic-web/dist not found -- run: cd comic-web && npm install && npm run build"
fi

cat > "$OUT/README-DEPLOY.md" <<'EOF'
# 部署包（由 scripts/package.sh 生成，请勿手工编辑）

## 目录

| 路径 | 内容 |
|---|---|
| `main.py` · `core/` · `routers/` · `services/` · `schemas.py` · `serializers.py` | HTTP 服务（api-service 分层代码）。⚠️ 这里的 `core/` 是 api 的 HTTP 分层包，与 `src/comic_core/` 无关 |
| `src/comic_core/` | 公共内核（领域模型 / 存储契约与 MySQL 实现 / 图库读写 / 标签归一） |
| `src/comic_crawler/` | 采集服务包（适配器 / 存储 / 调度 / CLI） |
| `dist/` | 前端构建产物（同源托管） |
| `sql/mysql_schema.sql` | 建库脚本 |
| `requirements.txt` | core + crawler + api 依赖合并 |

## 运行

```bash
python -m pip install -r requirements.txt
export COMIC_MYSQL_HOST=... COMIC_MYSQL_PORT=3309 COMIC_MYSQL_USER=root \
       COMIC_MYSQL_PASSWORD=... COMIC_IMAGE_ROOT=/srv/comic/data/image_store COMIC_JWT_SECRET=<强随机值>
python -m uvicorn main:app --host 0.0.0.0 --port 8000
```

- **不用设 `PYTHONPATH`**：`comic_core` / `comic_crawler` 放在 `src/` 下（刻意与开发树同构，
  好让 data 目录仍解析到 `<部署目录>/data/`），`main.py` 导入 `core.bootstrap` 时会自动把
  `<部署目录>/src` 注入 `sys.path`（见 api-service/core/bootstrap.py 的候选路径第 4 条）。
- ⚠️ 别把 `core/`（api 的 HTTP 分层包）和 `src/comic_core/`（公共内核）搞混，两者同名不同物。

- 首次部署先建库：`mysql -h <host> -P <port> -u root -p < sql/mysql_schema.sql`
- 运行时数据默认落在 `<部署目录>/data/`（图库 `data/image_store` + 源开关 `data/source_state.json`）；可用 `COMIC_IMAGE_ROOT` / `COMIC_STATE_FILE` 覆盖为共享目录（**须填绝对路径**，相对路径/`none` 之类的哨兵值会被忽略并告警）
- 站点首页 `/`、接口文档 `/docs`、采集管理台 `/#/admin`
EOF

# ---- 遗留检查（只报告，不删除）----
# 纯覆盖不会清掉"上一版有、这一版没有"的文件。重构改名/挪位置后（例如 adapter/ → sources/、
# mysql_storage.py → storage/mysql/），旧文件会一直赖在输出目录里 —— 这里把它们列出来。
echo
echo "-> check leftovers"
leftovers="$(
  for pair in \
    "core:$ROOT/api-service/core" \
    "routers:$ROOT/api-service/routers" \
    "services:$ROOT/api-service/services" \
    "src/comic_core:$ROOT/comic-core/src/comic_core" \
    "src/comic_crawler:$ROOT/crawler-service/src/comic_crawler" \
    "dist:$ROOT/comic-web/dist" \
    "sql:$ROOT/comic-core/sql"
  do
    sub="${pair%%:*}"; src="${pair#*:}"
    [ -d "$OUT/$sub" ] && [ -d "$src" ] || continue
    comm -13 \
      <( cd "$src"     && find . -type f ! -name "*.pyc" | sort ) \
      <( cd "$OUT/$sub" && find . -type f ! -name "*.pyc" | sort ) \
      | sed "s|^\./|  $sub/|"
  done
)"
if [ -n "$leftovers" ]; then
  echo "!! 以下文件在输出目录里存在、但源目录已没有（纯覆盖不会清除，属预期行为）："
  echo "$leftovers"
  echo "   → 确认无用后可手动删除；运行时数据 data/（图库、源开关状态）不在检查范围内"
else
  echo "   无遗留文件"
fi

echo
echo "OK  bundle ready: $OUT"
echo "    cd $OUT && python -m pip install -r requirements.txt"
echo "    python -m uvicorn main:app --host 0.0.0.0 --port 8000"
echo "    python -m uvicorn main:app --host 0.0.0.0 --port 8000"
