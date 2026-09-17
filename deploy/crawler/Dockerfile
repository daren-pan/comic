# crawler 模块 —— 采集层（可单独用：docker run --rm comic-crawler:1.0.0 python -m comic_crawler.cli list）
# 产物：deploy/build.sh 用 crawler-service/pyproject.toml 构建 wheel 到本目录 dist/
#
# 基础镜像经 DaoCloud 加速站拉取（m.daocloud.io 代理 docker.io）—— 国内直连 Docker Hub
# 拉 python:3.13-slim 常超时。要换回官方源，删掉 `m.daocloud.io/docker.io/library/` 前缀即可。
FROM m.daocloud.io/docker.io/library/python:3.13-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

# wheel 装进 site-packages 后，包位置的相对推导不再指向本项目 → 图库根必须显式给
ENV COMIC_IMAGE_ROOT=/data/image_store

WORKDIR /app

# 依赖源默认国内镜像（直连 pypi.org 很慢）。这一行装的是本层全部第三方依赖 —— 实测 19 个包 / 约 9MB。
# deploy/build.sh 会按「环境变量 PIP_INDEX → deploy/.env 的 PIP_INDEX → 这个默认值」传 --build-arg。
# 要换回官方源（海外/特殊网络）：docker build --build-arg PIP_INDEX=https://pypi.org/simple ...
ARG PIP_INDEX=https://mirrors.aliyun.com/pypi/simple
COPY dist/ /tmp/wheels/
RUN pip install --no-cache-dir --index-url "$PIP_INDEX" "$(ls -t /tmp/wheels/*.whl | head -1)"

# 非 root 运行；/data 先建好并改属主 —— 命名卷首次创建会继承镜像里该路径的属主，
# 否则以 uid 10001 运行的进程写不进去（表现为图库落不了盘）
RUN useradd -m -u 10001 comic \
 && mkdir -p /data/image_store \
 && chown -R comic:comic /data

USER comic
