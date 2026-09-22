"""请求体模型（Pydantic）。

只描述**入参形状与默认值**，不含校验以外的业务逻辑。

⚠️ **"策略"类校验仍写在 router / services 里**（那里能给出中文提示，并决定返 400 还是 404）：
注册的「用户名 3~32 位、密码 6~128 位」在 `routers/auth.py`，角色的合法取值在
`services/accounts.py`。本文件只声明**形状边界**（`max_length` / `ge`）。

为什么必须补上这些边界（2026-09-21 修补）：此前本文件几乎没有任何约束，越界入参
会一路走到 SQL 才炸 —— 实测两个**匿名可打的 500**：
`PUT /api/users/{uid}/history` 传不存在的 comicId 撞 `fk_hist_comic` 外键、
传超长 uid 撞 `history.user_id VARCHAR(64)`。入口拦掉后是 422，不再是 500。
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

# ---- 与库内列宽对齐的边界（超了必然写库失败，故在入口拦掉）----
MAX_SOURCE_LEN = 64      # comic.source / log_record.source VARCHAR(64)
MAX_KEYWORD_LEN = 2000   # 「封面自愈」的名称/ID 清单：够用，且防止拼出上千个 LIKE


class RegisterBody(BaseModel):
    """注册入参。长度策略（用户名 3~32、密码 6~128）在 `routers/auth.py` 判 —— 那里给中文提示。"""

    username: str
    password: str
    nickname: str = ""


class LoginBody(BaseModel):
    """登录入参（长度策略同上，见 `routers/auth.py`）。"""

    username: str
    password: str


class HistoryPut(BaseModel):
    """阅读进度入参。

    `comicId` / `chapterId` 必须是**正整数**：0 与负数在库里永远是无效主键，
    放行只会换来一次外键失败（500）。真正的"存不存在"由路由查库判（→ 404）。
    """

    comicId: int = Field(gt=0)
    chapterId: int = Field(gt=0)
    pageNo: int = Field(default=1, ge=1)


class AdminSyncBody(BaseModel):
    """采集入参。

    `mode` 用 `Literal` 收口：此前任意字符串都按"非 full 即 incremental"处理，
    写成 `mode="ful"` 这种笔误会**静默按增量跑**（用户以为跑了全量）。
    """

    source: str = Field(min_length=1, max_length=MAX_SOURCE_LEN)
    mode: Literal["incremental", "full"] = "incremental"
    since: str | None = None
    limit: int | None = Field(default=None, ge=1)   # 受控样本数：负数/0 无意义


class AdminInspectBody(BaseModel):
    """失效巡检入参（**全库维护的唯一入口**）：转存窗口内未转存页 + **全表**校验已转存对象
    + 全库封面自愈。

    source/since/until 只作用于「转存」部分；source 同时限定校验范围；全部留空 = 全库巡检。
    """

    source: str | None = Field(default=None, max_length=MAX_SOURCE_LEN)
    since: str | None = None
    until: str | None = None


class AdminHealBody(BaseModel):
    """封面自愈入参：**按作品**修复封面（`keyword` 必填，**不允许留空**）。

    `keyword`：漫画**名称或 ID**，可一次填多部 —— 逗号 / 空格 / 换行分隔，每项是 id 或名称
    （混填即可）。命中作品后**强制回源重抓封面并覆盖**，用于修「文件在但内容是错的」封面
    （普通自愈只看文件在不在，永远修不到错图）。
    `source`：可再按源收窄（AND）；留空 = 不限源。
    """

    keyword: str = Field(min_length=1, max_length=MAX_KEYWORD_LEN)
    source: str | None = Field(default=None, max_length=MAX_SOURCE_LEN)


class AdminImportBody(BaseModel):
    """按需导入入参：收录一部用户指定的作品（三选一提供定位方式）。

    - `keyword`：按书名/关键词让源站搜索，取其第一条作为目标（主入口）；
    - `ref`：作品页链接或作品 ID（适配器 parse_comic_ref 解析，次入口）；
    - `source_comic_id`：直接指定源站作品 ID（最精确）。

    `first_chapters` 留空 = **全量收目录**（按需导入的默认语义）；给数字则只收最新 N 话。
    导入**不下载正文图**：只写书目 + 全量章节 + 封面，正文图在阅读时按需取回。
    """

    source: str = Field(min_length=1, max_length=MAX_SOURCE_LEN)
    keyword: str | None = Field(default=None, max_length=MAX_KEYWORD_LEN)
    ref: str | None = Field(default=None, max_length=MAX_KEYWORD_LEN)
    source_comic_id: str | None = Field(default=None, max_length=128)
    first_chapters: int | None = Field(default=None, ge=1)


class AdminUserRoleBody(BaseModel):
    """授权页入参：给某个用户设置角色。

    取值只接受 `admin`（普通管理员）/ `user`（普通用户）—— **合法性在 `services/accounts.py`**
    里判（那里可单元测试），这里只描述形状。
    """

    role: str = Field(min_length=1, max_length=32)
