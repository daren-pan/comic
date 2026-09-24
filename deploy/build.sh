#!/usr/bin/env bash
# ============================================================
#  构建部署产物与镜像（分层：每个模块一个文件夹 + 一个 Dockerfile）
#
#  步骤 1  生成各模块产物到 deploy/<模块>/dist/
#             comic-core/        --wheel-->  deploy/core/dist/comic_core-<版本>.whl
#             crawler-service/   --wheel-->  deploy/crawler/dist/comic_crawler-<版本>.whl
#             api-service/       --wheel-->  deploy/api/dist/comic_api-<版本>.whl
#             <网页端产物目录>   --复制---->  deploy/web/dist/    （默认 comic-web/dist）
#             <移动端产物目录>   --复制---->  deploy/front/dist/  （默认 comic-front/dist/build/h5）
#  步骤 2  按依赖顺序构建镜像
#             mysql → web → crawler → api → front
#
#  其中 mysql 镜像是本项目**独占**的数据库（MySQL 8.0，见 docker-compose.yml）——数据卷首次
#  启动时会自动执行烘在镜像里的建库脚本，10 张表直接建好。
#          （api 构建时要读采集层的 wheel 产物，所以 crawler 的**产物**必须先出 —— 步骤 1 已保证。
#           两个模块之间**没有镜像依赖**：api 只是在 pyproject.toml 的 dependencies 里声明
#           comic-crawler，构建时由 pip 解析安装。）
#
#  ⚠️ comic-core 是**纯库、没有镜像** —— 它是 deploy/ 下唯一一个「只出 wheel、不建镜像」的模块，
#     所以 deploy/core/ 里只有 dist/（和一个说明用的 README.md），没有 Dockerfile。
#     它的 wheel 以 BuildKit **命名构建上下文 `core`** 喂给 crawler 与 api 两层
#     （见下面 build_img 调用处的 `--build-context core=./core`）——
#     少了它，pip 装 comic-crawler / comic-api 时会去 PyPI 找 comic-core 并直接报错。
#     wheel 的拓扑顺序固定为 **comic-core → crawler → api**（后两个的 METADATA 里声明了 comic-core）。
#
#  两个前端镜像（comic-web / comic-front）**各自带 nginx**：静态产物 + 反代在同一个容器里，
#  所以没有"反代活着但产物不在"的悬空状态。两个可以同时构建、同时运行，互不影响。
#  它们共用同一份 nginx 站点配置 —— deploy/web/nginx.conf 与 deploy/front/nginx.conf 必须
#  逐字节一致（Docker 构建上下文不能跨目录 COPY，只能各放一份），本脚本会先校验再构建。
#
#  用法：./deploy/build.sh                 # 两个前端都构建（默认）
#        ./deploy/build.sh --web           # 只构建网页端（comic-web:1.0.0）
#        ./deploy/build.sh --front         # 只构建移动端（comic-front:1.0.0）
#        ./deploy/build.sh --web --front   # 等价于不带参数
#        ./deploy/build.sh -h              （Windows: deploy\build.bat）
#        —— 一般**不用单独跑它**：一键脚本 `deploy/up.sh` 已经把
#           「前端 npm build → 本脚本 → compose up -d → 自检」串好了。
#        单独构建后启动：docker compose -f deploy/docker-compose.yml up -d
#
#  前端来源：网页端默认取 comic-web/dist，可用环境变量 **WEB_SRC=<目录>** 覆盖；
#        移动端默认取 comic-front/dist/build/h5，可用 **FRONT_SRC=<目录>** 覆盖。
#        两个产物目录在复制前都会先清空（避免不同 hash 的旧产物混在一起）。
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

# ---------- 参数：选要构建哪个前端（都不给 = 两个都建）----------
BUILD_WEB=0
BUILD_FRONT=0
for a in "$@"; do
  case "$a" in
    --web)   BUILD_WEB=1 ;;
    --front) BUILD_FRONT=1 ;;
    -h|--help)  # 打印文件头那段说明（按内容定位，不写死行号，免得改了头部就漏出正文）
                awk 'NR==1{next} {sub(/^# ?/,"")} NR>2 && /^=+$/ {print; exit} {print}' "$0"; exit 0 ;;
    *) echo "!! 未知参数：$a（-h 看用法）" >&2; exit 1 ;;
  esac
done
if [ "$BUILD_WEB" = "0" ] && [ "$BUILD_FRONT" = "0" ]; then
  BUILD_WEB=1
  BUILD_FRONT=1
fi

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
DEPLOY="$ROOT/deploy"

# 把相对路径按仓库根解析（绝对路径原样保留）
abs() {  # abs <路径>
  case "$1" in
    /*) printf '%s' "$1" ;;                    # POSIX 绝对路径
    [A-Za-z]:*) printf '%s' "$1" ;;            # Windows 盘符（C:/ 或 C:\）
    *) printf '%s' "$ROOT/$1" ;;               # 相对路径按仓库根解析
  esac
}

# 前端产物来源（见文件头）
WEB_SRC="$(abs "${WEB_SRC:-$ROOT/comic-web/dist}")"
FRONT_SRC="$(abs "${FRONT_SRC:-$ROOT/comic-front/dist/build/h5}")"

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

# ---------- 前置：两份 nginx.conf 必须逐字节一致 ----------
# 两个前端镜像各自带一份相同的站点配置（Docker 构建上下文不能跨目录 COPY），
# 所以改一处必须同步另一处 —— 这里先拦住，免得只有一边生效、排查半天。
# ⚠️ 比较时必须**先 cd 进 deploy/ 再用相对文件名**：$DEPLOY 在 Git Bash 里是 `/d/...` 形式，
#    直接交给 Windows 版 python.exe 会报 `FileNotFoundError: '/d/.../nginx.conf'`
#    （MSYS 只转换独立的参数，不转换嵌在 -c 字符串里的路径）—— 这与下面 docker/pip 一律用
#    相对路径是同一个原因。本机在 Git Bash 里跑 build.sh / up.sh 会因此整脚本起不来。
echo "-> [0/2] 校验两个前端镜像共用的 nginx 配置"
if ! ( cd "$DEPLOY" && "$PY" -c 'import filecmp,sys; sys.exit(0 if filecmp.cmp(sys.argv[1],sys.argv[2],shallow=False) else 1)' \
         web/nginx.conf front/nginx.conf ); then
  echo "   !! deploy/web/nginx.conf 与 deploy/front/nginx.conf 内容不一致"
  echo "      两个前端镜像共用同一份站点配置，必须逐字节相同。同步："
  echo "        cp deploy/web/nginx.conf deploy/front/nginx.conf"
  exit 1
fi
echo "   deploy/web/nginx.conf == deploy/front/nginx.conf ✅"

# ---------- 步骤 1：产物 ----------
echo
echo "-> [1/2] 生成模块产物到 deploy/<模块>/dist/"

build_wheel() {  # build_wheel <源模块目录> <deploy 子目录>
  local src="$1" out="$2"
  echo "   $src/  --wheel-->  deploy/$out/dist/"
  rm -rf "$DEPLOY/$out/dist" && mkdir -p "$DEPLOY/$out/dist"
  # ⚠️ 这里**必须用相对路径**：
  #   1) 源目录用 `.`（先 cd 进去）—— 传裸名字如 `api-service` 会被 pip 当成**包名**去 PyPI 找，
  #      而 PyPI 上真有个叫 api-service 的第三方包，会静默下回来一个假产物；
  #   2) 输出目录用 `../deploy/...` —— 传 "$ROOT/..." 这种绝对路径时，在 Windows 上可能是
  #      `/d/...` 形式，直接给 pip.exe 会报 `Invalid requirement: Expected package name ...`。
  ( cd "$ROOT/$src" && "$PY" -m pip wheel --disable-pip-version-check --no-deps --wheel-dir "../deploy/$out/dist" . >/dev/null )
}
# 拓扑顺序：comic-core 在最前 —— 后两个 wheel 的 METADATA 里声明了它
build_wheel comic-core      core
build_wheel crawler-service crawler
build_wheel api-service     api

echo "   comic-core/sql/mysql_schema.sql  --复制-->  deploy/mysql/sql/"
mkdir -p "$DEPLOY/mysql/sql"
cp "$ROOT/comic-core/sql/mysql_schema.sql" "$DEPLOY/mysql/sql/mysql_schema.sql"

# 复制前端产物（先清空目标目录：纯覆盖不会清除旧 hash 文件，两套产物会混在一起）
copy_front() {  # copy_front <源目录> <deploy 子目录> <人话名字>
  local src="$1" out="$2" label="$3"
  echo "   $src  --复制-->  deploy/$out/dist/"
  if [ ! -d "$src" ]; then
    echo "   !! $label 产物目录不存在：$src"
    echo "      先构建前端：$4"
    exit 1
  fi
  rm -rf "$DEPLOY/$out/dist"
  copy_tree "$src" "$DEPLOY/$out/dist" .
}

if [ "$BUILD_WEB" = "1" ]; then
  copy_front "$WEB_SRC"   web   "网页端" "cd comic-web && npm run build"
fi
if [ "$BUILD_FRONT" = "1" ]; then
  copy_front "$FRONT_SRC" front "移动端" "cd comic-front && npm run build:h5"
fi

# ---------- 产物检查 ----------
echo
echo "-> 产物检查"
for m in core crawler api; do
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

# 前端是文件复制，做一次遗留检查（只报告，不删除）
check_leftovers() {  # check_leftovers <源目录> <产物目录> <显示前缀>
  local src="$1" dist="$2" prefix="$3"
  local leftovers
  leftovers="$(
    comm -13 \
      <( cd "$src"  && find . -type f | sort ) \
      <( cd "$dist" && find . -type f | sort ) \
      | sed "s|^\./|        $prefix/|"
  )"
  if [ -n "$leftovers" ]; then
    echo "   !! 以下文件在产物目录里存在、但源目录已没有（纯覆盖不会清除，属预期行为）："
    echo "$leftovers"
    echo "      → 确认无用后手动删除"
  fi
}

if [ "$BUILD_WEB" = "1" ]; then
  echo "   deploy/web/dist/（$(find "$DEPLOY/web/dist" -type f | wc -l | tr -d ' ') 个文件）"
  check_leftovers "$WEB_SRC" "$DEPLOY/web/dist" "deploy/web/dist"
fi
if [ "$BUILD_FRONT" = "1" ]; then
  echo "   deploy/front/dist/（$(find "$DEPLOY/front/dist" -type f | wc -l | tr -d ' ') 个文件）"
  check_leftovers "$FRONT_SRC" "$DEPLOY/front/dist" "deploy/front/dist"
fi

# ---------- 步骤 2：按序构建镜像 ----------
echo
echo "-> [2/2] 构建镜像（顺序：mysql → web → crawler → api → front）"
# 用**相对路径**而不是绝对路径：Git Bash 的 pwd 给出 /d/... 这种 POSIX 形式，
# 直接传给 docker.exe（Windows 程序）会报 "unable to prepare context: path ... not found"。
cd "$DEPLOY"

# pip 依赖源（取值顺序见文件头）：crawler / api 两层认这个 ARG，其余层没声明它、会被静默忽略。
PIP_INDEX="${PIP_INDEX:-$(grep -E '^PIP_INDEX=' "$DEPLOY/.env" 2>/dev/null | tail -1 | cut -d= -f2- || true)}"
PIP_INDEX="${PIP_INDEX:-https://mirrors.aliyun.com/pypi/simple}"
echo "   [PyPI 源] $PIP_INDEX"

build_img() {  # build_img <模块目录> <镜像名> [额外的 docker build 参数...]
  local dir="$1" tag="$2"; shift 2
  docker build --no-cache --build-arg "PIP_INDEX=$PIP_INDEX" "$@" -t "$tag" "$dir"
}

build_img mysql   comic-mysql:1.0.0
# ⚠️ 这里必须写成 if/fi，不能用 `[ ... ] && build_img ...`：
#    脚本开了 set -e，条件为假时整个 AND 列表返回非 0，会让脚本在建镜像阶段直接退出
#    （症状：只跑 --front 时建完 mysql 就没了；只跑 --web 时建完 api 就没了）。
if [ "$BUILD_WEB" = "1" ]; then build_img web comic-web:1.0.0; fi
build_img crawler comic-crawler:1.0.0 --build-context "core=./core"
# api 要读**两个**上游 wheel 产物 → 挂两个命名上下文：
#   · core    —— 公共内核（deploy/core/dist/），Dockerfile 里 `COPY --from=core dist/`
#   · crawler —— 采集层（deploy/crawler/dist/），Dockerfile 里 `COPY --from=crawler dist/`
# **都不是镜像依赖**，所以顺序不是硬约束，只要两个 wheel 已生成即可（步骤 1 已保证）。
# 这里的相对路径按当前目录（= deploy/）解析。
build_img api     comic-api:1.0.0 --build-context "crawler=./crawler" --build-context "core=./core"
if [ "$BUILD_FRONT" = "1" ]; then build_img front comic-front:1.0.0; fi

echo
echo "OK  镜像已就绪"
docker images --format "  {{.Repository}}:{{.Tag}}\t{{.Size}}" | grep -E "comic-(mysql|web|crawler|api|front)" || true
echo
echo "启动：docker compose -f deploy/docker-compose.yml up -d"
echo "查看：docker compose -f deploy/docker-compose.yml ps"
