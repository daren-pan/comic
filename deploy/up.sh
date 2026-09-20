#!/usr/bin/env bash
# ============================================================
#  一键：构建前后端产物 + 镜像 → 启动整套服务 → 自检
#
#  依次做六件事：
#    0) 更新代码（`git pull`，只快进不合并；--skip-pull 跳过）
#    1) 前置检查（docker / compose v2 / deploy/.env / 运行时数据目录）
#    2) 构建前端产物 comic-web/dist（默认 npm run build）
#    3) 调 deploy/build.sh：生成 wheel、复制前端产物，按序构建 5 个镜像
#    4) docker compose up -d
#    5) 自检：mysql 健康 → 容器内接口可用 → 数据目录可写 → 对外入口 HTTP 码
#
#  用法：
#    bash deploy/up.sh                 # 全量：更新代码 + 前端 build + 镜像 build + 起服务
#    bash deploy/up.sh --skip-web      # 前端没改，跳过 npm build（快很多）
#    bash deploy/up.sh --skip-pull     # 不更新代码，直接按当前工作区构建
#    bash deploy/up.sh --collect       # 额外启动定时采集（comic-scheduler）
#    bash deploy/up.sh --migrate       # 起完服务后，对**已有库**跑一遍幂等迁移脚本
#                                      #   （老环境升级用；全新库不需要 —— 建表脚本已带全）
#    bash deploy/up.sh -h
#
#  说明：
#    · 脚本是**幂等**的 —— 重复跑就是更新代码 + 重新构建 + `up -d`，不会清数据；
#      真正会丢数据的只有 `docker compose down -v`（删数据库卷）与手动删数据目录。
#    · 开头会把代码更新到最新，并打出「更新了哪几条提交」，避免"改了没生效"；
#      只有拿不到新代码时（不是 git 工作区 / 断网 / 冲突）才按当前工作区继续构建。
#    · 前端产物是烘进 comic-api 镜像的（COPY --from=comic-web），所以改前端必须重跑本脚本。
# ============================================================
set -euo pipefail

SKIP_WEB=0
SKIP_PULL=0
COLLECT=0
MIGRATE=0
for a in "$@"; do
  case "$a" in
    --skip-web)  SKIP_WEB=1 ;;
    --skip-pull) SKIP_PULL=1 ;;
    --collect)   COLLECT=1 ;;
    --migrate)   MIGRATE=1 ;;
    -h|--help)  # 打印文件头那段说明（按内容定位，不写死行号，免得改了头部就漏出正文）
                awk 'NR==1{next} {sub(/^# ?/,"")} NR>2 && /^=+$/ {print; exit} {print}' "$0"; exit 0 ;;
    *) echo "!! 未知参数：$a（-h 看用法）" >&2; exit 1 ;;
  esac
done

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
DEPLOY="$ROOT/deploy"
cd "$DEPLOY"                      # 之后一律用**相对路径**调 docker/compose

step() { printf '\n== %s\n' "$*"; }
die()  { printf '!! %s\n' "$*" >&2; exit 1; }
# ⚠️ 必须用相对路径（`-f docker-compose.yml`）：在 Git Bash 里把 "$DEPLOY/..." 这种
#    `/d/...` MSYS 路径交给 docker.exe（Windows 程序）会被路径转换搞坏，报
#    `open D:\d\RuoyiProject\...: The system cannot find the path specified`。
#    这也是 build.sh 里一律用相对路径的同一个原因。
compose() { docker compose -f docker-compose.yml "$@"; }

# ---------- 0. 更新代码 ----------
# 「改了代码没生效」的头号原因就是漏了这一步（2026-09-18 排查）。放在最前面，
# 后面所有构建都按拉下来的代码走，省得靠人记得先 pull。
step "[0/6] 更新代码"
if [ "$SKIP_PULL" = "1" ]; then
  echo "   跳过（--skip-pull），按当前工作区构建"
elif ! command -v git >/dev/null 2>&1; then
  echo "   ⚠️ 没找到 git —— 跳过更新，按当前工作区构建"
elif ! git -C "$ROOT" rev-parse --git-dir >/dev/null 2>&1; then
  # 方式 C 的发布包 / 解压出来的目录没有 .git，属正常形态，不是错误
  echo "   ⚠️ $ROOT 不是 git 工作区（发布包形态？）—— 跳过更新，按现有文件构建"
else
  BEFORE="$(git -C "$ROOT" rev-parse HEAD)"
  echo "   pull 前 : $(git -C "$ROOT" log --oneline -1)"
  [ -z "$(git -C "$ROOT" status --porcelain 2>/dev/null || true)" ] \
    || echo "   ⚠️ 工作区有未提交改动 —— 可能与 pull 冲突（真失败会按当前工作区继续）"

  # --ff-only：服务器上只做快进，绝不在这里生成合并提交；有本地提交时会失败并给出提示。
  # 刻意不让 `set -e` 直接炸掉：pull 失败（断网 / 冲突）不该拦住"用现有代码起服务"。
  if PULL_OUT="$(git -C "$ROOT" pull --ff-only 2>&1)"; then
    AFTER="$(git -C "$ROOT" rev-parse HEAD)"
    if [ "$BEFORE" = "$AFTER" ]; then
      echo "   ✅ 已是最新，没有新提交（${AFTER:0:7}）"
    else
      N="$(git -C "$ROOT" rev-list --count "$BEFORE..$AFTER")"
      echo "   ✅ 代码已更新：${BEFORE:0:7} → ${AFTER:0:7}，共 $N 个新提交"
      git -C "$ROOT" log --oneline "$BEFORE..$AFTER" | sed 's/^/        /'
      # up.sh / build.sh 本身也在仓库里：这次拉下来的新版本要下一次跑才生效
      if git -C "$ROOT" diff --name-only "$BEFORE" "$AFTER" | grep -qE '^deploy/(up|build)\.sh$'; then
        echo "   ⚠️ 这次更新动了 deploy/up.sh 或 build.sh —— 当前跑的还是旧脚本，建议再跑一次"
      fi
    fi
  else
    echo "   ⚠️ git pull 失败 —— 按当前工作区继续构建。git 原话如下："
    printf '%s\n' "$PULL_OUT" | sed 's/^/        /'
    echo "        （想丢弃本地改动后重跑：git -C '$ROOT' checkout -- . && bash deploy/up.sh）"
  fi
fi

# ---------- 1. 前置检查 ----------
step "[1/6] 前置检查"
command -v docker >/dev/null 2>&1 || die "没找到 docker"
docker compose version >/dev/null 2>&1 \
  || die "需要 Docker Compose v2（命令形式是 'docker compose'，不是老的独立 'docker-compose'）"
docker info >/dev/null 2>&1 || die "Docker 守护进程不可用（本机装的是 Docker Desktop 吗？启动它）"
echo "   docker  : $(docker --version)"
echo "   compose : $(docker compose version --short 2>/dev/null || docker compose version | head -1)"

if [ ! -f "$DEPLOY/.env" ]; then
  cp "$DEPLOY/.env.example" "$DEPLOY/.env"
  echo "   已从 .env.example 生成 deploy/.env"
  die "请先编辑 deploy/.env：确认 MYSQL_ROOT_PASSWORD，并把 COMIC_JWT_SECRET 换成强随机值，然后重跑本脚本"
fi
echo "   deploy/.env 存在 ✅"

# 运行时数据目录（图库 + 源开关状态）：容器 bind 到它，本地直跑用的也是它
DATA_HOST="$(grep -E '^COMIC_DATA_HOST=' "$DEPLOY/.env" 2>/dev/null | tail -1 | cut -d= -f2- || true)"
DATA_HOST="${DATA_HOST:-}"
[ -n "$DATA_HOST" ] || DATA_HOST="$ROOT/crawler-service/data"
mkdir -p "$DATA_HOST/image_store"
# 以 root 跑（服务器上的常见情形）时顺手把属主设成容器内那个 uid，省掉一次踩坑
if [ "$(id -u 2>/dev/null || echo 1)" = "0" ]; then
  chown -R 10001:10001 "$DATA_HOST" 2>/dev/null || true
fi
[ -w "$DATA_HOST" ] || die "数据目录不可写：$DATA_HOST
   容器内进程以 uid 10001 运行，宿主上需执行：sudo chown -R 10001:10001 '$DATA_HOST'"
echo "   数据目录: $DATA_HOST ✅"

# ---------- 2. 前端 ----------
step "[2/6] 前端产物"
if [ "$SKIP_WEB" = "1" ]; then
  [ -d "$ROOT/comic-web/dist" ] || die "--skip-web 但 comic-web/dist 不存在，去掉该参数重跑"
  echo "   跳过（--skip-web），复用现有 comic-web/dist"
else
  command -v npm >/dev/null 2>&1 || die "没找到 npm —— 构建前端需要 Node.js 18+（只想跳过前端就用 --skip-web）"
  if [ ! -d "$ROOT/comic-web/node_modules" ]; then
    echo "   npm install（首次）"
    ( cd "$ROOT/comic-web" && npm install )
  fi
  echo "   npm run build"
  ( cd "$ROOT/comic-web" && npm run build )
  [ -d "$ROOT/comic-web/dist" ] || die "前端构建后仍然没有 comic-web/dist"
fi

# ---------- 3. 产物 + 镜像 ----------
step "[3/6] 生成 wheel/产物 + 按序构建 5 个镜像（mysql → web → crawler → api → nginx）"
bash "$DEPLOY/build.sh"

# ---------- 4. 起服务 ----------
step "[4/6] 启动服务"
if [ "$COLLECT" = "1" ]; then
  compose --profile collect up -d
else
  compose up -d
fi

# ---------- 4.5 已有库迁移（可选） ----------
if [ "$MIGRATE" = "1" ]; then
  step "[4.5] 迁移已有库（幂等；全新库可跳过）"
  echo "   挂载 ../tools 到容器 /app/tools，逐个跑（都支持重复执行）"
  for t in add_log_table.py add_perf_indexes.py drop_fingerprint_unique.py add_user_role.py; do
    echo "   → tools/$t"
    compose run --rm -v ../tools:/app/tools:ro comic-app python "tools/$t" \
      || die "tools/$t 失败 —— 单独跑它看详细输出：
  docker compose -f deploy/docker-compose.yml run --rm -v ../tools:/app/tools:ro comic-app python tools/$t"
  done
  echo "   ✅ 迁移脚本全部执行完（都是幂等的，没有改动就是已经迁过）"
  echo "   提示：add_user_role.py 若发现库里**没有超级管理员**，会把最早的特权用户提升为 superadmin"
  echo "         （转移超管身份：tools/add_user_role.py --superadmin <用户名>）"
  echo "         （否则升级后谁都进不去管理台）；之后的授权在管理台「授权」页做"
  echo "   提示：指纹（comic.fingerprint）只作"可能重复"的观察字段，若也要对齐可手动跑
         tools/rebuild_fingerprint.py（它会往容器内 /app/backup 写回滚 SQL，宿主上跑更方便）"
fi

# ---------- 5. 自检 ----------
step "[5/6] 自检"
for i in $(seq 1 40); do
  st="$(docker inspect comic-mysql --format '{{.State.Health.Status}}' 2>/dev/null || echo unknown)"
  if [ "$st" = "healthy" ]; then
    echo "   comic-mysql: healthy（第 ${i} 次探测）✅"
    break
  fi
  [ "$i" = "40" ] && die "comic-mysql 迟迟不 healthy —— 看日志：docker compose -f deploy/docker-compose.yml logs comic-mysql"
  sleep 3
done

# 应用能否连上库：在容器内打自己的接口（不依赖宿主机有没有 curl）
if compose exec -T comic-app python -c \
     "import urllib.request,json;print('   comic-app /api/health →',json.load(urllib.request.urlopen('http://127.0.0.1:8000/api/health',timeout=10))['data'])" 2>/dev/null; then
  echo "   ✅"
else
  die "comic-app 自检失败 —— 看日志：docker compose -f deploy/docker-compose.yml logs comic-app"
fi

# 数据目录可写性 —— bind 挂载最容易踩的坑（能读不能写，表现为转存落盘失败）
if compose exec -T comic-app sh -c 'touch /data/image_store/.probe && rm /data/image_store/.probe' 2>/dev/null; then
  echo "   /data/image_store 容器内可写 ✅"
else
  die "容器内写不了 /data/image_store —— 宿主目录属主要给 uid 10001：
   sudo chown -R 10001:10001 '$DATA_HOST'"
fi

# 对外入口（宿主有 curl 才验；服务器上一般都有）
# nginx 在 comic-app 的 uvicorn 真正开始监听前会返回 502，而 `up -d` 早就返回了，
# 所以要重试几次，而不是刚起来就打一枪。
PORT="$(grep -E '^HTTP_PORT=' "$DEPLOY/.env" 2>/dev/null | tail -1 | cut -d= -f2- || true)"
PORT="${PORT:-80}"
if command -v curl >/dev/null 2>&1; then
  code=""
  for _ in $(seq 1 12); do
    code="$(curl -s -o /dev/null -w '%{http_code}' --max-time 5 "http://127.0.0.1:$PORT/" 2>/dev/null || true)"
    case "$code" in
      000|502|503|504|"") sleep 2 ;;
      *) break ;;
    esac
  done
  echo "   对外入口 http://127.0.0.1:$PORT/ → HTTP ${code:-无响应}"
  if [ "$code" = "502" ]; then
    echo "   ⚠️ 502：nginx 已起，但上游 comic-app 还没就绪 —— 过几秒再试即可"
  fi
fi

# ---------- 6. 汇总 ----------
step "[6/6] 完成"
compose ps
cat <<EOF

  入口（宿主 HTTP_PORT=$PORT）
    站点        http://127.0.0.1:$PORT/
    管理台      http://127.0.0.1:$PORT/#/admin      （需管理员登录）
    授权页      http://127.0.0.1:$PORT/#/admin/users （给其他用户授权）
    接口文档    http://127.0.0.1:$PORT/docs

  ⚠️ 角色三档：superadmin 超管（管理台+日志+**授权页**，全库唯一）/ admin 普通管理员
     （管理台+日志，**进不了授权页**）/ user 普通用户（无权限）。
     全新库：**第一个注册的账号自动是超管**，部署完请立刻注册；
     已有库（老环境）记得带 --migrate 补 user.role 列并定下超管。

  数据位置（备份就这两处）
    数据库      Docker 卷 comic_mysql_data      （备份：mysqldump）
    图库/开关   $DATA_HOST

  常用命令
    更新部署  bash deploy/up.sh        # 先 git pull 再重建（代码已是最新则只重建）
    日志  docker compose -f deploy/docker-compose.yml logs -f comic-app
    状态  docker compose -f deploy/docker-compose.yml ps
    停止  docker compose -f deploy/docker-compose.yml down     # 卷与数据目录都保留
EOF
