# comic-chat 模块 —— RAG 客服服务（独立进程，内网 :8001）
#
# 产物：deploy/build.sh 用 chat-service/pyproject.toml 构建 wheel 到本目录 dist/
#
# ⚠️ 本层只装 wheel，**不依赖任何上游镜像**：comic-core 当命名上下文挂进来
#    （`COPY --from=core`）。漏了它，pip 装 comic-chat 时会去 PyPI 找 comic-core
#    并直接报错（PyPI 上不存在这个包）。
#    不需要 crawler 上下文 —— 本服务只借 comic-core 的模型、路径与存储。
#
# ⚠️ 为什么单独一个镜像而不是塞进 comic-api：
#    langchain / chromadb / fastembed 会拉进 80+ 个传递依赖，镜像涨 400MB 以上；
#    而且 bge 模型常驻需要 300~500MB 内存，和主站抢内存会被 OOM 杀掉（全站不可用）。
#    拆出来后 api 镜像保持原样，本服务崩了也只影响客服。
#
# ⚠️ 本文件刻意**不写** `# syntax=docker/dockerfile:1.4`：pin 前端版本会让每轮构建去拉
#    "语法镜像"的元数据 —— 镜像源抽风时（daocloud 502）直接挂构建（见 deploy/NOTES.md）。

FROM crpi-zu4tna9y8drenzc4.cn-hangzhou.personal.cr.aliyuncs.com/comic-website/python:3.13-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

# pip 源可被 compose 的 build.args 覆盖；默认用公开镜像源保证可构建。
ARG PIP_SOURCE=https://pypi.tuna.tsinghua.edu.cn/simple

COPY --from=core dist/ /tmp/wheels/core/
COPY dist/ /tmp/wheels/chat/

# 装 comic-chat 时 pip 读它 METADATA 里由 dependencies 生成的 Requires-Dist，
# 解析出 comic-core → 从 --find-links 指的本地目录取；其余第三方依赖走 PIP_SOURCE。
RUN --mount=type=cache,target=/root/.cache/pip pip install --index-url "$PIP_SOURCE" \
        --find-links /tmp/wheels/core \
        "$(ls -t /tmp/wheels/chat/*.whl | head -1)"

# ---- 预热向量模型（关键的一步）----
# 不做这一步，容器首次收到提问时要现下 90MB 模型，表现为「第一次问卡 30 秒」，
# 而健康检查是通的 —— 这种"看起来正常"的慢最难查。
# 模型名必须与 rag/settings.py 的 LOCAL_MODEL 默认值一致；改成别的模型时这里也要改。
ENV HF_HOME=/opt/hf-cache \
    HF_ENDPOINT=https://hf-mirror.com
RUN python -c "from fastembed import TextEmbedding; TextEmbedding('BAAI/bge-small-zh-v1.5')"

# 非 root 运行；/data 先建好并改属主 —— 命名卷首次创建会继承镜像里该路径的属主，
# 否则以 uid 10001 运行的进程写不进索引（表现为「重启后索引归零」）。
RUN useradd -m -u 10001 chat \
 && mkdir -p /data/rag_lab /opt/hf-cache \
 && chown -R chat:chat /data /opt/hf-cache

USER chat
EXPOSE 8001

# 单进程：bge 模型是进程内常驻的，多 worker 会成倍吃内存。
# 真要并发，先加副本（compose scale），别在容器里开 worker。
CMD ["python", "-m", "comic_chat"]
