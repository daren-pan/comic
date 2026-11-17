"""TaskBridge —— QQ 机器人到 coding agent 的任务网关。

链路：QQ → NapCat → LangBot（OneBot v11 流水线）→ Dify Chatflow → **TaskBridge** → opencode CLI + 模型
"""

__all__ = ["config", "store", "workspace", "agent", "worker"]
