"""请求体模型（Pydantic）。

只描述**入参形状与默认值**，不含校验以外的业务逻辑。
"""
from __future__ import annotations

from pydantic import BaseModel


class RegisterBody(BaseModel):
    username: str
    password: str
    nickname: str = ""


class LoginBody(BaseModel):
    username: str
    password: str


class HistoryPut(BaseModel):
    comicId: int
    chapterId: int
    pageNo: int = 1


class AdminSyncBody(BaseModel):
    source: str
    mode: str = "incremental"
    since: str | None = None
    limit: int | None = None


class AdminTransferBody(BaseModel):
    source: str | None = None
    since: str | None = None
    until: str | None = None
    # None = 不限制：把 source/since/until 所选范围内的未转存页全部转掉
    limit: int | None = None


class AdminInspectBody(BaseModel):
    """失效巡检入参：转存窗口内未转存页 + **全表**校验已转存对象是否还在。

    source/since/until 只作用于「转存」部分（与管理台转存同语义）；
    source 同时限定校验范围；全部留空 = 全库巡检。
    """

    source: str | None = None
    since: str | None = None
    until: str | None = None
