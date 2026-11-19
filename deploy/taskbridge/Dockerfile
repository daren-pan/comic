# comic-taskbridge —— 把 Dify 的「3 号线」指令落成真实代码改动的执行器
#
# 为什么需要 node：TaskBridge 调的是 opencode CLI（npm 包 opencode-ai），它本质是 Node 程序。
# 为什么还要 python：TaskBridge 本体是 FastAPI 服务。
#
# 仓库以 **可写 bind mount** 挂到 /repo：TaskBridge 要在里面建分支、跑 opencode 改文件、
# 提交、打 diff —— 挂只读就没法工作了。
#
# 构建上下文 = 仓库根（见 compose 的 context: ..）
FROM docker.m.daocloud.io/library/node:20-bookworm-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_INDEX_URL=https://mirrors.aliyun.com/pypi/simple \
    NPM_CONFIG_REGISTRY=https://registry.npmmirror.com

RUN apt-get update \
 && apt-get install -y --no-install-recommends \
        python3 python3-pip git ca-certificates curl \
 && rm -rf /var/lib/apt/lists/*

# TaskBridge 只依赖这三个；opencode 用 npm 全局装（Linux 下是可执行脚本，没有 .cmd 壳子问题）
RUN pip3 install --no-cache-dir --break-system-packages fastapi uvicorn pydantic \
 && npm install -g opencode-ai

# 容器内以 root 操作挂进来的仓库：git 会因「目录属主不符」拒绝，提前放行
# 仓库从 Windows 宿主挂进来（工作区是 CRLF）：容器里的 git 若不按同样的换行策略解释，
# 会把**整仓 400+ 个文件**都当成已修改 —— 基线被污染后，真实改动反而被过滤成「无改动」。
# fileMode 同理：WSL 挂载的可执行位与宿主不一致，也会产生假改动。
RUN git config --global --add safe.directory /repo \
 && git config --global --add safe.directory '*' \
 && git config --global core.autocrlf true \
 && git config --global core.fileMode false \
 && git config --global user.name 'taskbridge' \
 && git config --global user.email 'taskbridge@local'

WORKDIR /repo
ENV TB_REPO_ROOT=/repo \
    TB_HOST=0.0.0.0 \
    TB_PORT=8020 \
    TB_OPENCODE_BIN=/usr/local/bin/opencode

EXPOSE 8020

# run.py 会把 tools/ 塞进 sys.path，让 taskbridge 以普通包被导入
CMD ["python3", "taskbridge-service/run.py"]
