"""TaskBridge —— QQ 机器人到 coding agent 的任务网关。

链路：QQ（官方机器人 API）→ LangBot（qqofficial-omni 适配器）→ Dify Chatflow → **TaskBridge** → opencode CLI + 模型
"""

__all__ = ["config", "store", "workspace", "agent", "worker"]
