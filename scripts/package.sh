#!/usr/bin/env bash
# ============================================================
#  Package a deployable bundle (generated on demand; NOT committed).
#
#  Output layout <out>/ (default: build/deploy, override via $1):
#    main.py  core/  routers/  services/  schemas.py  serializers.py   <- HTTP layer (api-service)
#    src/comic_crawler/                                                 <- crawler package
#                                                                         (same shape as dev tree,
#                                                                          so image_store resolves to
#                                                                          <bundle>/image_store)
#    dist/                                                              <- frontend build output
#    sql/mysql_schema.sql                                               <- schema bootstrap
#    requirements.txt                                                   <- api + crawler deps (merged)
#    README-DEPLOY.md
#
#  Usage: ./scripts/package.sh [output-dir]
# ============================================================
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
OUT="${1:-$ROOT/build/deploy}"

rm -rf "$OUT"
mkdir -p "$OUT/src"

echo "-> copy HTTP layer (api-service)"
cp "$ROOT/api-service/main.py" "$ROOT/api-service/schemas.py" "$ROOT/api-service/serializers.py" "$OUT/"
cp -r "$ROOT/api-service/core" "$ROOT/api-service/routers" "$ROOT/api-service/services" "$OUT/"

echo "-> copy crawler package -> src/comic_crawler"
cp -r "$ROOT/crawler-service/src/comic_crawler" "$OUT/src/"

echo "-> merge requirements (api + crawler, dedup)"
sort -u "$ROOT/api-service/requirements.txt" "$ROOT/crawler-service/requirements.txt" > "$OUT/requirements.txt"

echo "-> copy schema"
mkdir -p "$OUT/sql"
cp "$ROOT/crawler-service/sql/mysql_schema.sql" "$OUT/sql/"

if [ -d "$ROOT/comic-web/dist" ]; then
  echo "-> copy frontend dist/"
  cp -r "$ROOT/comic-web/dist" "$OUT/dist"
else
  echo "!! comic-web/dist not found -- run: cd comic-web && npm install && npm run build"
fi

find "$OUT" -name "__pycache__" -type d -prune -exec rm -rf {} + 2>/dev/null || true
find "$OUT" -name "*.pyc" -delete 2>/dev/null || true

cat > "$OUT/README-DEPLOY.md" <<'EOF'
# 部署包（由 scripts/package.sh 生成，请勿手工编辑）

## 目录

| 路径 | 内容 |
|---|---|
| `main.py` · `core/` · `routers/` · `services/` · `schemas.py` · `serializers.py` | HTTP 服务（api-service 分层代码） |
| `src/comic_crawler/` | 采集服务包（适配器 / 存储 / 调度 / CLI） |
| `dist/` | 前端构建产物（同源托管） |
| `sql/mysql_schema.sql` | 建库脚本 |
| `requirements.txt` | api + crawler 依赖合并 |

## 运行

```bash
python -m pip install -r requirements.txt
export COMIC_MYSQL_HOST=... COMIC_MYSQL_PORT=3307 COMIC_MYSQL_USER=root \
       COMIC_MYSQL_PASSWORD=... COMIC_IMAGE_ROOT=/srv/comic/image_store COMIC_JWT_SECRET=<强随机值>
python -m uvicorn main:app --host 0.0.0.0 --port 8000
```

- 首次部署先建库：`mysql -h <host> -P <port> -u root -p < sql/mysql_schema.sql`
- 图库默认落在 `<部署目录>/image_store`（可用 `COMIC_IMAGE_ROOT` 覆盖为共享目录；**须填绝对路径**，相对路径/`none` 之类的哨兵值会被忽略并告警）
- 站点首页 `/`、接口文档 `/docs`、采集管理台 `/#/admin`
EOF

echo
echo "OK  bundle ready: $OUT"
echo "    cd $OUT && python -m pip install -r requirements.txt"
echo "    python -m uvicorn main:app --host 0.0.0.0 --port 8000"
