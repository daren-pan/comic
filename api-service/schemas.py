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


class AdminImportBody(BaseModel):
    """按需导入入参：收录一部用户指定的作品（三选一提供定位方式）。

    - `keyword`：按书名/关键词让源站搜索，取其第一条作为目标（主入口）；
    - `ref`：作品页链接或作品 ID（适配器 parse_comic_ref 解析，次入口）；
    - `source_comic_id`：直接指定源站作品 ID（最精确）。

    `first_chapters` 留空 = **全量收目录**（按需导入的默认语义）；给数字则只收最新 N 话。
    导入**不下载正文图**：只写书目 + 全量章节 + 封面，正文图在阅读时按需取回。
    """

    source: str
    keyword: str | None = None
    ref: str | None = None
    source_comic_id: str | None = None
    first_chapters: int | None = None


