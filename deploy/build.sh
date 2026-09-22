#!/usr/bin/env bash
# ============================================================
#  构建部署产物与镜像（分层：每个模块一个文件夹 + 一个 Dockerfile）
#
#  步骤 1  生成各模块产物到 deploy/<模块>/dist/
#             crawler-service/  --wheel-->  deploy/crawler/dist/comic_crawler-<版本>.whl
#             api-service/      --wheel-->  deploy/api/dist/comic_api-<版本>.whl
#             <前端产物目录>    --复制---->  deploy/web/dist/        （默认 comic-web/dist）
#  步骤 2  按依赖顺序构建镜像
#             mysql → web → crawler → api → nginx
#
#  其中 mysql 镜像是本项目**独占**的数据库（MySQL 8.0，见 docker-compose.yml）——数据卷首次
#  启动时会自动执行烘在镜像里的建库脚本，10 张表直接建好。
#          （顺序不能乱：api 的 Dockerfile 会 FROM comic-crawler:1.0.0 并 COPY --from=comic-web:1.0.0）
#
#  用法：./deploy/build.sh        （Windows: deploy\build.bat）
#        —— 一般**不用单独跑它**：一键脚本 `deploy/up.sh` 已经把
#           「前端 npm build → 本脚本 → compose up -d → 自检」串好了。
#        单独构建后启动：docker compose -f deploy/docker-compose.yml up -d
#
#  前端来源：默认取 comic-web/dist；可用环境变量 **WEB_SRC=<目录>** 换成别的前端产物 ——
#        `deploy/up-front.sh` 就是用它把 comic-front 的 H5 产物（dist/build/h5）喂进来的。
#        注意本脚本的复制是「合并覆盖」语义（见下面的 copy_tree），换来源前应先把
#        deploy/web/dist 清空，免得两个前端的 hash 产物混在一个目录里。
#
#  PyPI 源：镜像构建时装依赖走哪个源 —— 依次取 环境变量 PIP_INDEX → deploy/.env 的 PIP_INDEX
#        → 默认 https://mirrors.aliyun.com/pypi/simple（国内直连 pypi.org 很慢；
#        compose 不会替我们把 .env 里的键传给 docker build，所以必须在这里读出来显式传下去）。
#
#  依赖：构建 wheel 需要一个带 pip 的 Python 3.10+（优先取 PATH 里的 python3/python，
#        找不到或那个解释器没有 pip 时回落项目自带的 crawler-service/.venv；
#        也可用 PYTHON=/path/to/python 显式指定）。构建时 pip 会在临时隔离环境里装 setuptools。
# ============================================================
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
DEPLOY="$ROOT/deploy"

# 前端产物来源（见文件头）：默认 comic-web/dist，可用 WEB_SRC 换成别的前端产物目录。
WEB_SRC="${WEB_SRC:-$ROOT/comic-web/dist}"
case "$WEB_SRC" in
  /*) ;;                                      # POSIX 绝对路径
  [A-Za-z]:*) ;;                              # Windows 盘符（C:/ 或 C:\）
  *) WEB_SRC="$ROOT/$WEB_SRC" ;;              # 相对路径按仓库根解析
esac

# ---------- 选定 Python 解释器 ----------
# 优先级：PYTHON -> PATH 里的 python3/python -> 项目自带的 crawler-service/.venv。
# 最后这条回落是为「PATH 里的 python 装了但没 pip / 是别的用途的解释器」准备的
# （Windows 上很常见：python 指向 Microsoft Store 的占位程序）；
# 仓库里的 venv 一定有 pip，所以有它就能开箱跑通。
PY="${PYTHON:-}"
if [ -z "$PY" ]; then
  for c in python3 python; do
    command -v "$c" >/dev/null 2>&1 && PY="$c" && break
  done
fi
if [ -n "$PY" ] && ! "$PY" -m pip --version >/dev/null 2>&1; then PY=""; fi
if [ -z "$PY" ]; then
  for c in "$ROOT/crawler-service/.venv/bin/python3" "$ROOT/crawler-service/.venv/Scripts/python.exe"; do
    [ -x "$c" ] && "$c" -m pip --version >/dev/null 2>&1 && PY="$c" && break
  done
fi
[ -n "$PY" ] || {
  echo "!! 找不到带 pip 的 python"
  echo "   可显式指定：PYTHON=/path/to/python ./deploy/build.sh"
  echo "   或建一个 venv：python -m venv crawler-service/.venv"
  exit 1
}
echo "   使用 Python: $PY"

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
  ( cd "$ROOT/$src" && "$PY" -m pip wheel --disable-pip-version-check --no-deps --wheel-dir "../deploy/$out/dist" . >/dev/null )
}
build_wheel crawler-service crawler
build_wheel api-service     api

echo "   sql/mysql_schema.sql  --复制-->  deploy/mysql/sql/"
mkdir -p "$DEPLOY/mysql/sql"
cp "$ROOT/crawler-service/sql/mysql_schema.sql" "$DEPLOY/mysql/sql/mysql_schema.sql"

echo "   $WEB_SRC  --复制-->  deploy/web/dist/"
if [ -d "$WEB_SRC" ]; then
  copy_tree "$WEB_SRC" "$DEPLOY/web/dist" .
else
  echo "   !! 前端产物目录不存在：$WEB_SRC"
  echo "      先构建前端：cd comic-web && npm run build   或   cd comic-front && npm run build:h5"
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
    <( cd "$WEB_SRC" && find . -type f | sort ) \
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

# pip 依赖源（取值顺序见文件头）：crawler / api 两层认这个 ARG，其余层没声明它、会被静默忽略。
PIP_INDEX="${PIP_INDEX:-$(grep -E '^PIP_INDEX=' "$DEPLOY/.env" 2>/dev/null | tail -1 | cut -d= -f2- || true)}"
PIP_INDEX="${PIP_INDEX:-https://mirrors.aliyun.com/pypi/simple}"
echo "   [PyPI 源] $PIP_INDEX"

build_img() {  # build_img <模块目录> <镜像名>
  docker build --build-arg "PIP_INDEX=$PIP_INDEX" -t "$2" "$1"
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
