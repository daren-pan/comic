# api 模块 —— 接口层（**纯 API**，不托管前端）
#
# 产物：deploy/build.sh 用 api-service/pyproject.toml 构建 wheel 到本目录 dist/
#
# 依赖上游两个模块的**方式**：都只要它们的 **wheel 产物**，构建时经 BuildKit
# 命名上下文挂进来 —— 见 deploy/build.sh：
#   · core    = ./core    （公共内核，deploy/core/dist/）      → `COPY --from=core dist/`
#   · crawler = ./crawler （采集层，  deploy/crawler/dist/）   → `COPY --from=crawler dist/`
# 与 docker-compose.yml 的 `additional_contexts` 也是同一对。
# ⚠️ **不再 `FROM comic-crawler:1.0.0`**（2026-09-24 解耦）：模块之间的依赖只有两处声明，
#    就是 api-service/pyproject.toml 的 `dependencies` 里那两句
#    `comic-core>=1.0.0` 与 `comic-crawler>=1.0.0`（方向单向：api → crawler → core）。
#    所以**不需要先有 crawler 镜像**，只要那两个 wheel 已生成。
#
# ⚠️ 前端不烘进这里：网页端与移动端各自带 nginx（deploy/web/ 与 deploy/front/），
#    后端只在内网提供 /api/* —— 既不需要 comic-web 镜像，也不需要 COMIC_DIST_DIR。
#    main.py 那层挂载有 `if DIST_DIR.is_dir()` 守卫：目录不存在就自然不挂，无需改后端代码。

# 基础镜像经 DaoCloud 加速站拉取（m.daocloud.io 代理 docker.io，与 crawler 层同一个来源）——
# 国内直连 Docker Hub 拉 python:3.13-slim 常超时。要换回官方源，删掉前缀即可。
FROM m.daocloud.io/docker.io/library/python:3.13-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

# 图库与源开关状态都落在 /data（compose 里 bind 到宿主运行时数据目录）。
# wheel 装进 site-packages 后，包位置的相对推导不再指向本项目 → 图库根必须显式给。
ENV COMIC_IMAGE_ROOT=/data/image_store \
    COMIC_STATE_FILE=/data/source_state.json

WORKDIR /app

# 依赖源同 crawler 层：默认国内镜像，由 deploy/build.sh 传 --build-arg 覆盖
ARG PIP_INDEX=https://mirrors.aliyun.com/pypi/simple

# 三个 wheel 都进构建上下文：
#   · api       —— 本目录产物（COPY dist/）；
#   · core      —— 公共内核产物，走命名上下文（COPY --from=core）；
#   · crawler   —— 采集层产物，走命名上下文（COPY --from=crawler）。
# ⚠️ 三者都放 /tmp/wheels/ 的**各自子目录**下（不混在一层）——
#    crawler 那层的 Dockerfile 用 `ls -t /tmp/wheels/*.whl | head -1` 挑包，
#    平铺会让它挑错；本层同理，用 --find-links 分别指向才不会装错。
# 装 comic-api 时 pip 会读它 METADATA 里由 dependencies 生成的 Requires-Dist，
# 依次解析出 comic-crawler 与 comic-core → 从 --find-links 指的本地目录取；
# 其余第三方依赖仍走 PIP_INDEX。
COPY --from=core dist/ /tmp/wheels/core/
COPY --from=crawler dist/ /tmp/wheels/crawler/
COPY dist/ /tmp/wheels/api/
RUN pip install --no-cache-dir --index-url "$PIP_INDEX" \
        --find-links /tmp/wheels/core \
        --find-links /tmp/wheels/crawler \
        "$(ls -t /tmp/wheels/api/*.whl | head -1)"

# 非 root 运行；/data 先建好并改属主 —— 命名卷首次创建会继承镜像里该路径的属主，
# 否则以 uid 10001 运行的进程写不进去（表现为图库落不了盘）
RUN useradd -m -u 10001 comic \
 && mkdir -p /data/image_store \
 && chown -R comic:comic /data

USER comic
EXPOSE 8000

# 单进程：内存任务表与开关状态尚未改造，多 worker 会导致"任务查不到"
CMD ["python", "-m", "uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
