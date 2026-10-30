"""请求体模型（Pydantic）。

只声明**形状边界**，不含业务逻辑 —— 和 api-service 同一分工：
真正的策略（阈值、取几条）在 `rag/chain.py`，这里只挡明显越界（空问题、topK 超范围）。

⚠️ 面向用户的 `/ask` 刻意只收一个问题：`topK` / `kind` / `minScore` 是调参开关，
不该由前台传 —— 否则用户能绕过阈值去翻无关内容。要调参走 `/lab/*`（管理员）。
"""
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


class Turn(BaseModel):
    """一轮对话（`/ask` 的 `history` 元素）。

    `role` 只有两种：`user` = 用户说的，`bot` = 客服答的。
    """

    role: Literal["user", "bot"]
    content: str = Field(max_length=500)


class AskBody(BaseModel):
    """客服提问（`POST /ask`）。

    `history` 由前端带上来（后端不存会话）：最多 **12 条**（6 轮），每条 500 字。
    ⚠️ 上限在这里卡死是有意的 —— 前端可以篡改，不设限的话一次请求就能把几十轮历史
    塞进 prompt（既贵又会挤掉参考资料）。超了直接 422，不静默截断。
    """

    question: str = Field(min_length=1, max_length=200)
    history: list[Turn] = Field(default_factory=list, max_length=12)


class SearchBody(BaseModel):
    """检索调试（`POST /lab/search`）——字段含义与 `rag/chain.py` 的 `search()` 一一对应。"""

    question: str = Field(min_length=1, max_length=500)
    topK: int | None = Field(default=None, ge=1, le=20)
    kind: Literal["faq", "comic"] | None = None
    #: 不传 = 用后端默认阈值；传 0 = 不过滤（想看全部候选时用）
    minScore: float | None = Field(default=None, ge=-1.0, le=1.0)


class LabAskBody(BaseModel):
    """问答调试（`POST /lab/ask`）——比面向用户的 `/ask` 多两个调参项和一个调试字段。"""

    question: str = Field(min_length=1, max_length=500)
    topK: int | None = Field(default=None, ge=1, le=20)
    kind: Literal["faq", "comic"] | None = None
    #: 是否返回「实际发给模型的参考资料」——学习/排查时最该看这一段
    withContext: bool = True
