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


class AdminScheduleBody(BaseModel):
    """「定时任务」保存入参（管理台「定时任务」栏）。

    节奏用 **5 段 cron**（`分 时 日 月 周`）表达 —— 「每天定点」与「每隔一段时间」
    已合并成同一个表达式：

    | 想要的效果 | 表达式 |
    |---|---|
    | 每天 03:00（默认） | `0 3 * * *` |
    | 每隔 15 分钟 | `*/15 * * * *` |
    | 每 6 小时 | `0 */6 * * *` |
    | 每周一 03:00 | `0 3 * * 1` |

    这里只收口**形状**（非空、长度 ≤ 64）；段数 / 取值范围 / 步长的语义校验在
    `services.scheduler.update()` 里用 `parse_cron` 做，非法返 **400** 并带上段名与原因
    （唯一定义处是 crawler 的 `scheduling/cron.py`）。

    每轮对 `sources` 里的每个源执行一次采集（`mode` 增量/全量，`limit` / `since` 透传，
    与「触发采集」是同一套参数、最终调同一个 `admin_jobs.sync_job`）。

    `sources` 留空 = 全部「**代码里默认启用**」的源（`mangadex` 因 AUP 非商用默认关闭）；
    定时任务**不看**管理台那张开关 —— 它按"参数即准入"运行。要采集默认关闭的源
    （如 `mangadex`），必须在这里显式点名。
    """

    enabled: bool = False
    #: 5 段 cron（`分 时 日 月 周`）。默认值与旧的「每天 03:00」等价 ——
    #: 见 crawler 的 `scheduling/cron.py`（`DEFAULT_CRON`）。
    cron: str = Field(default="0 3 * * *", min_length=1, max_length=64)
    #: 这一轮干什么：`sync` = 逐源采集（默认）、`inspect` = 失效巡检
    #: （转存未转存页 + 全表校验 + 恢复丢失；**不含**手动巡检那步全库封面自愈）。
    #: ⚠️ `inspect` 时 `mode`/`limit` 无意义，`sources` 恰好点名一个源才限定范围，否则全库。
    action: Literal["sync", "inspect"] = "sync"
    sources: list[str] = Field(default_factory=list)
    mode: Literal["incremental", "full"] = "incremental"
    limit: int | None = Field(default=None, ge=1)
    since: str | None = None


class AdminUserRoleBody(BaseModel):
    """授权页入参：给某个用户设置角色。

    取值只接受 `admin`（普通管理员）/ `user`（普通用户）—— **合法性在 `services/accounts.py`**
    里判（那里可单元测试），这里只描述形状。
    """

    role: str = Field(min_length=1, max_length=32)


class MessageBody(BaseModel):
    """发一条消息（`POST /api/messages`）—— **其他模块的写入入口**。

    `kind` 刻意**不用 Literal 收口**：这是个开放写入接口，别的模块可以有自定义消息类型
    （任务消息用任务类型 `sync`/`inspect`/`heal`/`import`/`schedule`；其余如 `system`/`notice`）。
    但**长度上限必须有** —— 这些值直接落 VARCHAR 列，超长要么被静默截断、要么报错。
    `level` 则收口成三档（前端据此显示 完成/警告/失败），非法值在存储层兜成 `info`。

    **收件范围**（两个条件同时成立才可见；都不填 = 所有登录用户）：
    - `toUserId`：定向发给某个人；
    - `minRole` ：最低角色要求（`''`/`user` < `admin` < `superadmin`；`admin` 时超管也看得到）。
      采集/巡检这类**任务**消息请传 `admin` —— 那是管理台的事，普通用户不需要看。
    ⚠️ `minRole` 用 `Literal` 收口（写错了会静默发给所有人，比 422 危险），
      非法的角色值会直接 422 报错。
    """

    kind: str = Field(default="system", max_length=16)
    level: Literal["info", "warn", "error"] = "info"
    title: str = Field(min_length=1, max_length=255)
    body: str = Field(default="", max_length=4000)
    #: 入参快照（可选）：任务类消息放 `{"since": "2026-10-01", "mode": "incremental", "limit": 1}` ——
    #: 列表里据此显示"这条消息说的是哪段时间范围内的数据"。存储层会截断到 2000 字符。
    params: dict | None = None
    taskId: str = Field(default="", max_length=64)
    source: str = Field(default="", max_length=64)
    userId: int | None = None
    username: str = Field(default="", max_length=64)
    toUserId: int | None = None
    minRole: Literal["", "user", "admin", "superadmin"] = ""
