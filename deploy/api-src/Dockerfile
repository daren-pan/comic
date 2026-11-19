# comic-api（源码挂载版）—— 本地 / 开发环境的 API 容器
#
# 与 deploy/api/Dockerfile 的区别：
#   · 那份是**生产镜像**：先由 deploy/build.sh 把三个模块打成 wheel，再 COPY 进镜像，
#     代码烘死在镜像里，改代码要重建。
#   · 本份是**开发容器**：只装第三方依赖，代码靠 compose 的 bind mount 挂进来，
#     改完代码重启容器即可，不必重建镜像，也不依赖 wheel 产物与 ACR 基础镜像。
#
# 为什么需要它：Dify 的 HTTP 节点要访问宿主 8000（host.docker.internal:8000），
# 而 comic-app 默认不映射宿主端口；且它的镜像没构建过。这个服务用于本机联调。
#
# 构建上下文 = 仓库根（见 compose 里的 context: ..）
FROM docker.m.daocloud.io/library/python:3.13-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_INDEX_URL=https://mirrors.aliyun.com/pypi/simple

WORKDIR /repo

# 依赖清单单独 COPY 一层：改代码不会让依赖层失效
COPY comic-core/requirements.txt /tmp/req-core.txt
COPY crawler-service/requirements.txt /tmp/req-crawler.txt
COPY api-service/requirements.txt /tmp/req-api.txt

# 三个模块的依赖一起装（api 在进程内调用 crawler，crawler 依赖 core）
RUN pip install --no-cache-dir \
        -r /tmp/req-core.txt \
        -r /tmp/req-crawler.txt \
        -r /tmp/req-api.txt

# 源码走 bind mount；这里只需要让 import 找得到两个上游模块
ENV PYTHONPATH=/repo/comic-core/src:/repo/crawler-service/src

WORKDIR /repo/api-service
EXPOSE 8000
CMD ["python", "-m", "uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
