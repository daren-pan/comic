# api 模块 —— 接口层（FastAPI + 同源托管前端）
# 产物：deploy/build.sh 用 api-service/pyproject.toml 构建 wheel 到本目录 dist/
# 依赖：需先建好 comic-web:1.0.0 与 comic-crawler:1.0.0（顺序固定在 deploy/build.sh）
ARG CRAWLER_IMAGE=comic-crawler:1.0.0
FROM ${CRAWLER_IMAGE}

# wheel 落进 site-packages 后相对推导失效 → 这两项必须显式给
ENV COMIC_DIST_DIR=/app/comic-web/dist \
    COMIC_STATE_FILE=/data/source_state.json

USER root

# 依赖源同 crawler 层：默认国内镜像，由 deploy/build.sh 传 --build-arg 覆盖（见 crawler/Dockerfile 的注释）
ARG PIP_INDEX=https://mirrors.aliyun.com/pypi/simple
COPY dist/ /tmp/wheels/
RUN pip install --no-cache-dir --index-url "$PIP_INDEX" "$(ls -t /tmp/wheels/*.whl | head -1)"

# 前端产物取自 web 模块镜像（所以后端镜像里不需要 Node）
COPY --from=comic-web:1.0.0 --chown=comic:comic /app/dist /app/comic-web/dist

USER comic
WORKDIR /app
EXPOSE 8000

# 单进程：内存任务表与开关状态尚未改造，多 worker 会导致"任务查不到"
CMD ["python", "-m", "uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
