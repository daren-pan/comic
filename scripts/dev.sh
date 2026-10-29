#!/usr/bin/env bash
# scripts/dev.sh —— 本地开发环境：状态 / 启动 / 停止
#
# 用法：
#   bash scripts/dev.sh status
#   bash scripts/dev.sh up api|web|front        # 前台运行（agent 用 run_in_background=true）
#   bash scripts/dev.sh down api|web|front|all
#   bash scripts/dev.sh bootstrap               # 手动创建 / 补齐 python 环境（一般不用手动跑）
#
# 约定：
#   - 前端优先标准命令 npm run dev / npm run dev:h5；npm 不可用时自动回退 node 直调 bin
#     （2026-10-22 复查：npm 已由 WorkBuddy 受管 Node 接管，可正常使用；见 NOTES §2.1）
#   - python 是**两层、都在项目内**（都进 .gitignore，不碰系统 python）：
#       `.python/`              基础解释器：官方 CPython（版本见 PY_VERSION），缺了自动下载解压
#       `crawler-service/.venv` 运行环境：由 `.python` 创建，装三份 requirements
#     两者都不存在或依赖不全时，`up api` 会自动建齐（见 ensure_python / ensure_env）。
#     版本锁 3.13 —— 与线上镜像 python:3.13-slim 对齐，不做自动降级。
#   - 停止按端口找 PID（taskkill //PID），禁用 taskkill /IM（会误伤同机其他服务）
set -u

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT" || exit 1

# ── python 环境（项目内两层：.python 底座 + crawler-service/.venv 运行环境）──
PY_VERSION="3.13.17"                    # 基础解释器版本（官方 nuget 构建，锁 3.13.x）
PY_HOME="$ROOT/.python"
PY_BASE="$PY_HOME/python.exe"; [ -x "$PY_BASE" ] || PY_BASE="$PY_HOME/bin/python3"

VENV="$ROOT/crawler-service/.venv"
PY="$VENV/Scripts/python.exe"
[ -x "$PY" ] || PY="$VENV/bin/python"

# 环境完整性判据：这一组能一起 import 就算齐了，缺一个就补装（比 marker 文件可靠）
ENV_IMPORTS="fastapi,uvicorn,httpx,parsel,pymysql,cryptography,zhconv,bcrypt,jwt,python_multipart"
PIP_DEFAULT_INDEX="https://mirrors.aliyun.com/pypi/simple"

py_minor()   { "$1" -c 'import sys;print("%d.%d"%sys.version_info[:2])' 2>/dev/null; }
# 统一路径形态再比较：Git Bash 的 /d/x 与 Python 报告的 d:/x 是同一条路径，直接比会误判
norm_path()  {
  local p
  p="$(echo "$1" | tr '\\' '/' | tr '[:upper:]' '[:lower:]')"
  case "$p" in
    /[a-z]/*) p="${p#/}"; p="${p:0:1}:/${p:2}" ;;
  esac
  echo "$p" | sed 's:/*$::'
}
venv_home()  { sed -n 's/^home *= *//p' "$1/pyvenv.cfg" 2>/dev/null | tr -d '\r'; }

# 下载并展开官方 CPython 到 .python/（仅 Windows：nuget 上是官方 Windows 构建）
# 返回 0=装好 1=失败 2=平台不支持
install_python() {
  local url tmp
  case "$(uname -s)" in
    MINGW*|MSYS*|CYGWIN*) ;;
    *) return 2 ;;
  esac
  command -v curl  >/dev/null 2>&1 || { echo "❌ 需要 curl 才能下载 Python"  >&2; return 1; }
  command -v unzip >/dev/null 2>&1 || { echo "❌ 需要 unzip 才能解压 Python" >&2; return 1; }
  url="https://api.nuget.org/v3-flatcontainer/python/$PY_VERSION/python.$PY_VERSION.nupkg"
  # 临时目录放项目内（.python.tmp，已 gitignore）：mktemp 在 Git Bash 下返回
  # `C:\...\Temp/tmp.xxx` 这种带盘符的混合路径，会被删除守卫拒绝，且散落在系统临时目录没人清
  tmp="$ROOT/.python.tmp"
  rm -rf "$tmp" 2>/dev/null || true
  mkdir -p "$tmp" || { echo "❌ 创建 $tmp 失败" >&2; return 1; }
  echo "[env] 下载 Python $PY_VERSION（约 15MB，官方 nuget 构建）…"
  if ! curl -fL --retry 2 -m 300 -o "$tmp/py.nupkg" "$url"; then
    echo "❌ 下载失败（检查网络）" >&2; return 1
  fi
  echo "[env] 解压到 .python/ …"
  ( cd "$tmp" && unzip -q py.nupkg ) || { echo "❌ 解压失败" >&2; return 1; }
  [ -x "$tmp/tools/python.exe" ] || { echo "❌ 包结构异常：缺 tools/python.exe" >&2; return 1; }
  # 旧底座不直接删（删除守卫会拦，且删一半更糟）——先挪开，装好后再尽力清理
  if [ -e "$PY_HOME" ]; then
    mv "$PY_HOME" "$PY_HOME.old-$(date +%s)" || { echo "❌ 旧的 .python 无法移开（可能被占用）" >&2; return 1; }
  fi
  mv "$tmp/tools" "$PY_HOME" || { echo "❌ 移动到 .python/ 失败" >&2; return 1; }
  rm -rf "$tmp" 2>/dev/null || echo "[env] ⚠ 临时目录留在 $tmp（可手动删，已 gitignore）"
  rm -rf "$PY_HOME".old-* 2>/dev/null || true
  PY_BASE="$PY_HOME/python.exe"
  echo "[env] ✅ 基础解释器就绪：$("$PY_BASE" -V 2>&1)（$PY_HOME）"
}

# 确保 .python/ 存在且是 3.13
ensure_python() {
  local v rc c
  if [ -x "$PY_BASE" ]; then
    v="$(py_minor "$PY_BASE")"
    [ "$v" = "3.13" ] && return 0
    echo "[env] 项目内 python 是 ${v:-未知}，期望 3.13 —— 重新安装" >&2
  fi
  install_python; rc=$?
  [ "$rc" -eq 0 ] && return 0
  if [ "$rc" -eq 2 ]; then
    # 非 Windows：拿系统 python 3.13 当底座（不给 Linux 下载便携 CPython，避免多一套来源）
    for c in python3.13 python3; do
      command -v "$c" >/dev/null 2>&1 || continue
      [ "$(py_minor "$c")" = "3.13" ] || continue
      PY_BASE="$(command -v "$c")"
      echo "[env] 非 Windows：用系统 $c 作基础解释器（项目内 .python/ 只提供 Windows 构建）"
      return 0
    done
    echo "❌ 需要 Python 3.13 才能创建环境" >&2
    echo "   Ubuntu / Debian：sudo apt install python3.13-venv" >&2
    echo "   macOS：brew install python@3.13" >&2
  fi
  return 1
}

# ensure_env [venv 目录] —— 底座就位 → venv 存在且底座一致 → 依赖齐全；幂等
ensure_env() {
  local dir="${1:-$VENV}" py want got old_venv=""
  ensure_python || return 1
  py="$dir/Scripts/python.exe"; [ -x "$py" ] || py="$dir/bin/python"

  # 底座一致性：venv 的 pyvenv.cfg home 必须是项目内 .python（Windows 场景）
  if [ -x "$py" ] && [ -d "$PY_HOME" ]; then
    want="$(norm_path "$PY_HOME")"
    got="$(norm_path "$(venv_home "$dir")")"
    if [ -n "$got" ] && [ "$got" != "$want" ]; then
      echo "[env] $dir 的底座是 $got，不是项目内 .python —— 重建以统一环境…"
      # 先挪开再建：直接 rm 会被删除守卫拦（也可能删一半），挪开是可回退的
      old_venv="${dir}.old-$(date +%s)"
      mv "$dir" "$old_venv" || { echo "❌ 旧 venv 无法移开（可能被占用）：$dir" >&2; return 1; }
      py="$dir/Scripts/python.exe"; [ -x "$py" ] || py="$dir/bin/python"
    fi
  fi

  if [ ! -x "$py" ]; then
    echo "[env] 未找到 $dir（首次或新克隆），开始创建…"
    "$PY_BASE" -m venv "$dir" || {
      echo "❌ venv 创建失败（Debian 系缺 ensurepip 时先 apt install python3-venv）" >&2; return 1; }
    py="$dir/Scripts/python.exe"; [ -x "$py" ] || py="$dir/bin/python"
    [ -x "$py" ] || { echo "❌ venv 里没有 python：$dir" >&2; return 1; }
  fi

  # 建完必须核对底座，否则会"看起来成功、其实还挂在旧解释器上"
  if [ -d "$PY_HOME" ]; then
    want="$(norm_path "$PY_HOME")"
    got="$(norm_path "$(venv_home "$dir")")"
    [ "$got" = "$want" ] || {
      echo "❌ 新建的 venv 底座仍不一致：$got（期望 $want）" >&2; return 1; }
  fi
  if ! "$py" -c "import $ENV_IMPORTS" >/dev/null 2>&1; then
    echo "[env] 安装依赖（comic-core / crawler-service / api-service）…"
    "$py" -m pip install -q --disable-pip-version-check -U pip >/dev/null 2>&1 || true
    "$py" -m pip install -q --disable-pip-version-check \
      --index-url "${PIP_INDEX:-$PIP_DEFAULT_INDEX}" \
      -r "$ROOT/comic-core/requirements.txt" \
      -r "$ROOT/crawler-service/requirements.txt" \
      -r "$ROOT/api-service/requirements.txt" || {
      echo "❌ 依赖安装失败（网络 / 源问题；可用 PIP_INDEX=<镜像> 重试）" >&2; return 1; }
    "$py" -c "import $ENV_IMPORTS" >/dev/null 2>&1 || {
      echo "❌ 装完仍缺依赖，请检查 requirements.txt" >&2; return 1; }
    echo "[env] ✅ 依赖就绪（$("$py" -V 2>&1)）"
  fi
  if [ -n "$old_venv" ]; then
    rm -rf "$old_venv" 2>/dev/null && echo "[env] 已清理旧 venv：$(basename "$old_venv")" \
      || echo "[env] ⚠ 旧 venv 未清理：$old_venv（可手动删）"
  fi
  # 顺手清理历史遗留（之前中断留下的 .old-*），失败不影响使用
  rm -rf "$dir".old-* 2>/dev/null || true
  return 0
}

port_of() {
  case "$1" in
    api) echo 8000 ;;
    chat) echo 8001 ;;    # RAG 客服（独立进程；api 通过 COMIC_CHAT_SERVICE_URL 调它）
    web) echo 5173 ;;
    front) echo 5174 ;;
    *) echo "" ;;
  esac
}

port_pid() {
  local port="$1" line
  line="$(netstat -ano 2>/dev/null | tr -d '\r' | grep -E "[:.]${port}[[:space:]].*LISTENING" | head -1)"
  [ -n "$line" ] && echo "$line" | sed -E 's/.*[[:space:]]([0-9]+)[[:space:]]*$/\1/' || echo ""
}

http_code() {
  # 注意：路径参数不要以 / 开头 —— Git Bash(MSYS) 会把 "/api/health" 转成 Windows 路径，
  # 传给 node 后变成 GET D%3A/.../api/health（404）。所以传 "api/health"，在 JS 里补斜杠。
  node -e '
    const http = require("http");
    const req = http.get(
      { host: "127.0.0.1", port: Number(process.argv[1]), path: "/" + process.argv[2], timeout: 1500 },
      (r) => { console.log(r.statusCode); r.resume(); }
    );
    req.on("timeout", () => { req.destroy(); console.log("TIMEOUT"); });
    req.on("error", () => console.log("DOWN"));
  ' "$1" "$2" 2>/dev/null
}

# ── 前置条件检测（只检测 + 给操作指引，不替用户装）──────────────────
# mysql 状态：healthy / starting / unhealthy / running / stopped / missing / no-docker / docker-down
mysql_probe() {
  if ! command -v docker >/dev/null 2>&1; then echo no-docker; return; fi
  if ! docker info >/dev/null 2>&1; then echo docker-down; return; fi
  local st
  st="$(docker inspect -f '{{if .State.Health}}{{.State.Health.Status}}{{else}}{{.State.Status}}{{end}}' comic-mysql 2>/dev/null | tr -d '\r')"
  case "$st" in
    healthy|starting|unhealthy|running) echo "$st" ;;
    exited|created|paused|dead) echo stopped ;;
    "") echo missing ;;                      # 容器压根没建过（新机器就是这种）
    *) echo "$st" ;;
  esac
}

mysql_tip() {  # mysql_tip <mysql_probe 的状态>
  case "$1" in
    no-docker)   printf '   没找到 docker 命令：先安装 Docker（https://docs.docker.com/engine/install/）后重试\n' ;;
    docker-down) printf '   docker 命令在，但守护进程没响应：启动 Docker 服务后重试（Linux: sudo systemctl start docker）\n' ;;
    missing)     printf '   数据库容器还没创建过，起一次（会构建 mysql 镜像，约 1~2 分钟）：\n'
                 printf '     docker compose -f deploy/docker-compose.yml up -d comic-mysql\n' ;;
    stopped)     printf '   容器存在但没在跑：docker start comic-mysql\n' ;;
    starting)    printf '   容器正在启动，等十几秒再试；看状态：docker ps --filter name=comic-mysql\n' ;;
    unhealthy)   printf '   在跑但健康检查没过：docker logs comic-mysql --tail 50\n' ;;
    *)           printf '   看详细状态：docker ps -a --filter name=comic-mysql\n' ;;
  esac
}

# 前端前置：node 存在 + 版本够 + 依赖已装（不自动装，只给指引）
check_front() {  # check_front web|front
  local t="$1" dir name bin major
  case "$t" in
    web)   dir="$ROOT/comic-web";   name="comic-web";   bin="node_modules/vite/bin/vite.js" ;;
    front) dir="$ROOT/comic-front"; name="comic-front"; bin="node_modules/@dcloudio/vite-plugin-uni/bin/uni.js" ;;
  esac
  if ! command -v node >/dev/null 2>&1; then
    echo "❌ 前置条件不满足：没找到 node（前端需要 Node.js 18+）" >&2
    echo "   装 Node LTS：https://nodejs.org/ （或用 WorkBuddy 自带的受管 Node）" >&2
    return 1
  fi
  major="$(node -p 'process.versions.node.split(".")[0]' 2>/dev/null)"
  if [ -n "$major" ] && [ "$major" -lt 18 ] 2>/dev/null; then
    echo "❌ 前置条件不满足：Node 版本过低（当前 $(node -v 2>/dev/null)，需要 18+）" >&2
    echo "   升级：https://nodejs.org/ 或 nvm install 20" >&2
    return 1
  fi
  if [ ! -d "$dir/node_modules" ]; then
    echo "❌ 前置条件不满足：$name 还没装依赖（node_modules 不存在）" >&2
    echo "   装一次即可（首次约 1~3 分钟）：cd $name && npm ci" >&2
    return 1
  fi
  if [ ! -f "$dir/$bin" ]; then
    echo "❌ 前置条件不满足：$name/node_modules 不完整（缺 $bin）" >&2
    echo "   可能是上次装到一半中断，重装：cd $name && npm ci" >&2
    return 1
  fi
  return 0
}

cmd_status() {
  echo "── 本地开发环境状态 ─────────────────────────"
  local ms t port pid code wf ff
  ms="$(mysql_probe)"
  if [ "$ms" = "healthy" ]; then
    echo "  $(printf '%-7s' mysql) comic-mysql：healthy"
  else
    echo "  $(printf '%-7s' mysql) comic-mysql：⛔ $ms"
    mysql_tip "$ms"
  fi
  wf="✅"; [ -d "$ROOT/comic-web/node_modules" ]   || wf="⛔ 未装"
  ff="✅"; [ -d "$ROOT/comic-front/node_modules" ] || ff="⛔ 未装"
  echo "  $(printf '%-7s' deps) web $wf · front $ff"
  [ "$wf" != "✅" ] && echo "          cd comic-web && npm ci"
  [ "$ff" != "✅" ] && echo "          cd comic-front && npm ci"
  if [ -x "$PY_BASE" ]; then
    echo "  $(printf '%-7s' base) .python/（$("$PY_BASE" -V 2>&1 | sed 's/^Python //')）"
  else
    echo "  $(printf '%-7s' base) ⛔ .python/ 不存在（up api 时自动下载）"
  fi
  if [ -x "$PY" ]; then
    echo "  $(printf '%-7s' python) crawler-service/.venv（$("$PY" -V 2>&1 | sed 's/^Python //')）"
  else
    echo "  $(printf '%-7s' python) ⛔ crawler-service/.venv 不存在（up api 时自动创建）"
  fi
  for t in api chat web front; do
    port="$(port_of "$t")"
    pid="$(port_pid "$port")"
    if [ -n "$pid" ]; then
      if [ "$t" = "api" ]; then
        code="$(http_code 8000 api/health)"
        echo "  $(printf '%-7s' "$t") :$port  ✅ 运行中 (PID $pid) · /api/health $code"
      else
        echo "  $(printf '%-7s' "$t") :$port  ✅ 运行中 (PID $pid)"
      fi
    else
      echo "  $(printf '%-7s' "$t") :$port  ⛔ 未启动"
    fi
  done
  echo "  日志    logs/api.log · logs/chat.log（chat）· logs/vite.log（web）· logs/vite-front.log（front）"
  echo "─────────────────────────────────────────────"
}

cmd_up() {
  local t="$1" port pid
  if [ -z "$(port_of "$t")" ]; then
    echo "用法：bash scripts/dev.sh up api|chat|web|front（前台运行，agent 请加 run_in_background=true）"
    exit 2
  fi
  port="$(port_of "$t")"
  pid="$(port_pid "$port")"
  if [ -n "$pid" ]; then
    echo "[$t] 已在运行（PID $pid，端口 $port），无需重复启动"
    return 0
  fi

  case "$t" in
    api)
      local ms
      ms="$(mysql_probe)"
      if [ "$ms" != "healthy" ]; then
        echo "❌ 前置条件不满足：MySQL 未就绪（当前：$ms）" >&2
        mysql_tip "$ms" >&2
        exit 1
      fi
      ensure_env "$VENV" || exit 1
      PY="$VENV/Scripts/python.exe"; [ -x "$PY" ] || PY="$VENV/bin/python"
      echo "[api] 启动 uvicorn → http://127.0.0.1:8000  （日志：logs/api.log）"
      echo "[api] 解释器：$PY（crawler-service/.venv）"
      cd "$ROOT/api-service" || exit 1
      exec "$PY" -m uvicorn main:app --host 127.0.0.1 --port 8000 >> "$ROOT/logs/api.log" 2>&1
      ;;
    chat)
      # RAG 客服是**独立进程**：它要装 langchain/chromadb/fastembed（80+ 个包），
      # 塞进 api 进程既拖慢启动也跟主站抢内存 —— 见 chat-service/README.md。
      echo "[chat] 启动 comic-chat → http://127.0.0.1:8001  （日志：logs/chat.log）"
      cd "$ROOT/chat-service" || exit 1
      PY="$VENV/Scripts/python.exe"; [ -x "$PY" ] || PY="$VENV/bin/python"
      # 两个本地包都要进 path：本模块 src + 公共内核 comic-core/src。
      # ⚠️ 分隔符按平台给：Windows 是分号，Linux/macOS 是冒号 —— 用错了 Python 会把整串
      #    当成一个路径，import comic_core 直接失败。
      case "$(uname -s)" in
        MINGW*|MSYS*|CYGWIN*) export PYTHONPATH="src;../comic-core/src" ;;
        *)                    export PYTHONPATH="src:../comic-core/src" ;;
      esac
      # 本地只监听回环，不暴露到局域网（容器里才需要 0.0.0.0）
      export COMIC_CHAT_HOST=127.0.0.1 COMIC_CHAT_PORT=8001
      exec "$PY" -m comic_chat >> "$ROOT/logs/chat.log" 2>&1
      ;;
    web)
      check_front web || exit 1
      echo "[web] 启动 vite → http://127.0.0.1:5173  （日志：logs/vite.log）"
      cd "$ROOT/comic-web" || exit 1
      if npm --version >/dev/null 2>&1; then
        exec npm run dev >> "$ROOT/logs/vite.log" 2>&1
      fi
      echo "[web] npm 不可用，回退 node 直调 vite" >> "$ROOT/logs/vite.log"
      exec node node_modules/vite/bin/vite.js >> "$ROOT/logs/vite.log" 2>&1
      ;;
    front)
      check_front front || exit 1
      echo "[front] 启动 uni（H5）→ http://127.0.0.1:5174  （日志：logs/vite-front.log）"
      cd "$ROOT/comic-front" || exit 1
      if npm --version >/dev/null 2>&1; then
        exec npm run dev:h5 >> "$ROOT/logs/vite-front.log" 2>&1
      fi
      echo "[front] npm 不可用，回退 node 直调 uni" >> "$ROOT/logs/vite-front.log"
      exec node node_modules/@dcloudio/vite-plugin-uni/bin/uni.js >> "$ROOT/logs/vite-front.log" 2>&1
      ;;
  esac
}

cmd_bootstrap() {
  local dir="${1:-$VENV}"
  ensure_env "$dir" || exit 1
  echo "[bootstrap] ✅ 环境就绪：$dir"
  case "$dir" in
    "$VENV") echo "[bootstrap]    scheduler / tools 也用这个解释器" ;;
  esac
}

cmd_down() {
  local targets="$1" t port pid
  [ "$targets" = "all" ] && targets="api web front"
  for t in $targets; do
    port="$(port_of "$t")"
    if [ -z "$port" ]; then echo "[$t] 未知目标，跳过"; continue; fi
    pid="$(port_pid "$port")"
    if [ -z "$pid" ]; then echo "[$t] 未在运行（:$port 无监听）"; continue; fi
    echo "[$t] 停止 PID $pid（:$port）"
    if taskkill //PID "$pid" //F >/dev/null 2>&1; then
      echo "  ✅ 已停止"
    else
      echo "  ⚠ taskkill 失败（PID $pid），请手动处理"
    fi
  done
}

case "${1:-status}" in
  status) cmd_status ;;
  up) cmd_up "${2:-}" ;;
  down) cmd_down "${2:-all}" ;;
  bootstrap) cmd_bootstrap "${2:-}" ;;
  *)
    echo "用法：bash scripts/dev.sh status | up api|web|front | down api|web|front|all | bootstrap"
    exit 2
    ;;
esac
