#!/usr/bin/env bash
# ============================================================
#  构建部署产物与镜像（分层：每个模块一个文件夹 + 一个 Dockerfile）
#
#  步骤 1  生成各模块产物到 deploy/<模块>/dist/
#             crawler-service/  --wheel-->  deploy/crawler/dist/comic_crawler-<版本>.whl
#             api-service/      --wheel-->  deploy/api/dist/comic_api-<版本>.whl
#             comic-web/dist/   --复制---->  deploy/web/dist/
#  步骤 2  按依赖顺序构建镜像
#             mysql → web → crawler → api → nginx
#
#  其中 mysql 镜像当前**不被编排使用**（项目复用现有的 MySQL 实例，见 docker-compose.yml
#  末尾「数据库」），构建它只为"需要一个独立干净的库"时备用 —— 它与被复用的实例同版本
#  （5.7），且数据卷首次启动时会自动执行我们的建库脚本。
#          （顺序不能乱：api 的 Dockerfile 会 FROM comic-crawler:1.0.0 并 COPY --from=comic-web:1.0.0）
#
#  用法：./deploy/build.sh        （Windows: deploy\build.bat）
#        构建完启动：docker compose -f deploy/docker-compose.yml up -d
#
#  依赖：构建 wheel 需要一个带 pip 的 Python 3.10+（默认取 PATH 里的 python3/python，
#        可用 PYTHON=/path/to/python 覆盖）。构建时 pip 会在临时隔离环境里装 setuptools。
# ============================================================
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
DEPLOY="$ROOT/deploy"

# ---------- 选定 Python 解释器 ----------
PY="${PYTHON:-}"
if [ -z "$PY" ]; then
  for c in python3 python; do
    command -v "$c" >/dev/null 2>&1 && PY="$c" && break
  done
fi
[ -n "$PY" ] || { echo "!! 找不到 python —— 可用 PYTHON=/path/to/python 指定"; exit 1; }
"$PY" -m pip --version >/dev/null 2>&1 || { echo "!! $PY 里没有可用的 pip"; exit 1; }

copy_tree() {  # copy_tree <源根> <目标目录> <相对路径...>；目标已存在时合并内容而非嵌套
  local src="$1" dest="$2"
  shift 2
  mkdir -p "$dest"
  ( cd "$src" && tar -cf - --exclude='__pycache__' --exclude='*.pyc' "$@" ) | ( cd "$dest" && tar -xf - )
}

# ---------- 步骤 1：产物 ----------
echo "-> [1/2] 生成模块产物到 deploy/<模块>/dist/"

build_wheel() {  # build_wheel <源模块目录> <deploy 子目录>
  local src="$1" out="$2"
  echo "   $src/  --wheel-->  deploy/$out/dist/"
  mkdir -p "$DEPLOY/$out/dist"
  # ⚠️ 这里**必须用相对路径**：
  #   1) 源目录用 `.`（先 cd 进去）—— 传裸名字如 `api-service` 会被 pip 当成**包名**去 PyPI 找，
  #      而 PyPI 上真有个叫 api-service 的第三方包，会静默下回来一个假产物；
  #   2) 输出目录用 `../deploy/...` —— 传 "$ROOT/..." 这种绝对路径时，在 Windows 上可能是
  #      `/d/...` 形式，直接给 pip.exe 会报 `Invalid requirement: Expected package name ...`。
  ( cd "$ROOT/$src" && "$PY" -m pip wheel --no-deps --wheel-dir "../deploy/$out/dist" . >/dev/null )
}
build_wheel crawler-service crawler
build_wheel api-service     api

echo "   sql/mysql_schema.sql  --复制-->  deploy/mysql/sql/"
mkdir -p "$DEPLOY/mysql/sql"
cp "$ROOT/crawler-service/sql/mysql_schema.sql" "$DEPLOY/mysql/sql/mysql_schema.sql"

echo "   comic-web/dist  --复制-->  deploy/web/dist/"
if [ -d "$ROOT/comic-web/dist" ]; then
  copy_tree "$ROOT/comic-web/dist" "$DEPLOY/web/dist" .
else
  echo "   !! comic-web/dist 不存在 —— 先构建前端：cd comic-web && npm run build"
  exit 1
fi

# ---------- 产物检查 ----------
echo
echo "-> 产物检查"
for m in crawler api; do
  n=$(ls -1 "$DEPLOY/$m/dist"/*.whl 2>/dev/null | wc -l | tr -d ' ')
  if [ "$n" -eq 0 ]; then
    echo "   !! deploy/$m/dist/ 下没有 whl —— 构建失败了？"
  elif [ "$n" -gt 1 ]; then
    # 版本号变过之后旧包会留下；镜像里取最新那个，但留着一堆容易看混
    echo "   !! deploy/$m/dist/ 下有 $n 个 whl（版本变更残留），镜像只装最新的；建议手动删旧的："
    ls -1 "$DEPLOY/$m/dist"/*.whl | sed 's|.*/|        |'
  else
    echo "   deploy/$m/dist/$(ls -1 "$DEPLOY/$m/dist" | head -1)"
  fi
done
echo "   deploy/web/dist/（$(find "$DEPLOY/web/dist" -type f | wc -l | tr -d ' ') 个文件）"

# 前端是文件复制，做一次遗留检查（只报告，不删除）
leftovers="$(
  comm -13 \
    <( cd "$ROOT/comic-web/dist" && find . -type f | sort ) \
    <( cd "$DEPLOY/web/dist" && find . -type f | sort ) \
    | sed 's|^\./|        deploy/web/dist/|'
)"
if [ -n "$leftovers" ]; then
  echo "   !! 以下文件在产物目录里存在、但源目录已没有（纯覆盖不会清除，属预期行为）："
  echo "$leftovers"
  echo "      → 确认无用后手动删除"
fi

# ---------- 步骤 2：按序构建镜像 ----------
echo
echo "-> [2/2] 构建镜像（顺序：mysql → web → crawler → api → nginx）"
# 用**相对路径**而不是绝对路径：Git Bash 的 pwd 给出 /d/... 这种 POSIX 形式，
# 直接传给 docker.exe（Windows 程序）会报 "unable to prepare context: path ... not found"。
cd "$DEPLOY"

# PIP_INDEX 是可选的（见文件头）：传了就让 crawler / api 两层换源装依赖。
build_img() {  # build_img <模块目录> <镜像名>
  if [ -n "${PIP_INDEX:-}" ]; then
    echo "   [PyPI 源] $PIP_INDEX"
    docker build --build-arg "PIP_INDEX=$PIP_INDEX" -t "$2" "$1"
  else
    docker build -t "$2" "$1"
  fi
}

build_img mysql   comic-mysql:1.0.0
build_img web     comic-web:1.0.0
build_img crawler comic-crawler:1.0.0
build_img api     comic-api:1.0.0
build_img nginx   comic-nginx:1.0.0

echo
echo "OK  镜像已就绪"
docker images --format "  {{.Repository}}:{{.Tag}}\t{{.Size}}" | grep -E "comic-(mysql|web|crawler|api|nginx)" || true
echo
echo "启动：docker compose -f deploy/docker-compose.yml up -d"
echo "查看：docker compose -f deploy/docker-compose.yml ps"
