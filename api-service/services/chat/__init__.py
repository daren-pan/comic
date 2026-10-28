"""services 下的对话/客服域（当前只有 RAG 实验室）。

主链路（智能客服）尚未实现 —— 本包现阶段只承载 `lab/`。

## 为什么 `lab/` 是独立子包、且延迟导入

实验室要用 LangChain + Chroma（80 多个传递依赖）。这套东西**不进生产镜像**：
依赖声明单独放在 `api-service/requirements-lab.txt`，`deploy/` 的 Dockerfile 不装它。

因此本包和 `lab/` 的 `__init__` 里**不做任何重型 import** —— 没装 langchain 时，
`import services.chat` 仍然成功，api 正常启动；只有真正调用 lab 功能时才会
在函数内部 import，并给出「请先装 requirements-lab.txt」的中文提示。
"""
from __future__ import annotations

# api-service 的 sys.path 引导（comic_core 等本地包）。lab 的 settings 一导入就要用
# `comic_core.paths`，所以引导必须发生在包初始化阶段 —— 放在这里比每个子模块各写一遍干净。
from core import bootstrap  # noqa: F401
