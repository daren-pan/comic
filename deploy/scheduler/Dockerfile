# scheduler 模块 —— 定时任务执行器（独立进程，管理台「定时任务」栏的执行侧）
#
# 产物：deploy/build.sh 用 comic-scheduler/pyproject.toml 构建 wheel 到本目录 dist/
#
# 依赖上游两个模块的**方式**：都只要它们的 **wheel 产物**，构建时经 BuildKit
# 命名上下文挂进来 —— 见 deploy/build.sh：
#   · core    = ./core    （公共内核，deploy/core/dist/）      → `COPY --from=core dist/`
#   · crawler = ./crawler （采集层，  deploy/crawler/dist/）   → `COPY --from=crawler dist/`
# 与 docker-compose.yml 的 `additional_contexts` 也是同一对。
# ⚠️ 与 api 那层同理：模块之间的依赖只有一处声明，就是 comic-scheduler/pyproject.toml 的
#    `dependencies` 里那两句 `comic-core>=1.0.0` 与 `comic-crawler>=1.0.0`
#    （方向单向：scheduler → crawler → core）。所以**不需要先有 crawler 镜像**。
#
# ⚠️ 与 api 镜像的区别：这里**没有** HTTP 端口、没有前端、也没有 uvicorn ——
#    它是一个常驻的守护进程（每 5s 看一次表），靠 SIGTERM 干净退出（`docker stop`）。

# 基础镜像经 DaoCloud 加速站拉取（m.daocloud.io 代理 docker.io，与 crawler/api 层同一来源）——
# 国内直连 Docker Hub 拉 python:3.13-slim 常超时。要换回官方源，删掉前缀即可。
FROM m.daocloud.io/docker.io/library/python:3.13-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

# 运行时数据都在 /data（compose 里 bind 到宿主运行时数据目录）。
# wheel 装进 site-packages 后，包位置的相对推导不再指向本项目 → 这几个路径必须显式给，
# 否则本进程会去写**镜像内部**的 data 目录：管理台配的 cron 读不到、"立即执行"也收不到
# （表现为"配了不跑"，且日志里看不到任何触发）。
# 三个文件的职责见 comic-scheduler/README.md。
ENV COMIC_IMAGE_ROOT=/data/image_store \
    COMIC_STATE_FILE=/data/source_state.json \
    COMIC_SCHEDULE_FILE=/data/schedule.json \
    COMIC_SCHEDULE_STATE_FILE=/data/schedule_state.json \
    COMIC_SCHEDULE_TRIGGER_FILE=/data/schedule_run_now.json

# 消息中心：写完一轮就往 api 发一条消息（**写入只走 HTTP**，见 comic_core/notify.py）。
# 容器里 api 的服务名是 comic-app；服务令牌复用 COMIC_JWT_SECRET（由 compose 注入，不在这里写死）。
ENV COMIC_API_BASE=http://comic-app:8000

WORKDIR /app

# 依赖源同 crawler/api 层：默认国内镜像，由 deploy/build.sh 传 --build-arg 覆盖
ARG PIP_INDEX=https://mirrors.aliyun.com/pypi/simple

# 三个 wheel 都进构建上下文，且**各自放子目录**（不混在一层）——
# api 那层说明了原因：`ls -t /tmp/wheels/*.whl | head -1` 这种挑包方式会被平铺的 whl 挑错。
# 装 comic-scheduler 时 pip 会读它 METADATA 里由 dependencies 生成的 Requires-Dist，
# 依次解析出 comic-crawler 与 comic-core → 从 --find-links 指的本地目录取；
# 其余第三方依赖仍走 PIP_INDEX。
COPY --from=core dist/ /tmp/wheels/core/
COPY --from=crawler dist/ /tmp/wheels/crawler/
COPY dist/ /tmp/wheels/scheduler/
RUN pip install --no-cache-dir --index-url "$PIP_INDEX" \
        --find-links /tmp/wheels/core \
        --find-links /tmp/wheels/crawler \
        "$(ls -t /tmp/wheels/scheduler/*.whl | head -1)"

# 非 root 运行；/data 先建好并改属主 —— 命名卷首次创建会继承镜像里该路径的属主，
# 否则以 uid 10001 运行的进程写不进去（表现为运行态 / 图库落不了盘）
RUN useradd -m -u 10001 comic \
 && mkdir -p /data/image_store \
 && chown -R comic:comic /data

USER comic

# 每 5s 看一次表；Ctrl+C / docker stop 都能干净退出（见 daemon.py 的信号处理）
CMD ["python", "-m", "comic_scheduler"]
