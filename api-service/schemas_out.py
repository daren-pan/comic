"""响应模型（出参契约）—— 与 `schemas.py`（入参）对称，是**接口返回形状的唯一声明处**。

## 为什么要有这个文件（2026-10-13）

此前响应形状**只存在于函数体里**：`serializers.to_comic()` 手写一个 dict 字面量，
路由再 `return ok({...})` 包一层。后果有三条：

1. **OpenAPI 看不到响应**（实测）：`/openapi.json` 里 46 个 path 的
   `responses.200.schema` **全是 `None`**，`components.schemas` 里 18 个模型**全是入参**。
   → `/docs` 上"响应"栏是空白的，前端也拿不到可生成的类型（`types.ts` 342 行只能手抄）。
2. **类型靠驱动好心**：`to_comic` 里 `views`/`favoriteCount`/`heat` 都套了 `int()`，
   唯独 `chapterCount` 没套 —— 今天侥幸没事（驱动给的是 int），换连接参数就会把字符串
   流到前端，而前端类型写着 `number`，没有任何东西会报错。
3. **契约变更无人感知**：字段改名/少返回，要等线上报错才知道。

本文件把形状变成**声明**：一处定义、可被校验、可被 OpenAPI 读取。
`serializers.to_*()` 改为**构造**这些模型（转换逻辑不变），路由声明 `response_model`。

## ⚠️ 三条硬约束（改这个文件前必读）

1. **必须完整覆盖返回字段** —— `response_model` 会**静默丢弃未声明的字段**
   （改前裸 dict 不过滤）。漏一个字段 = 前端某字段变 `undefined`，后端不报错、日志也没有。
   守卫见 `tests/test_response_contract.py`。
2. **类型必须容纳现存数据的所有实际取值** —— 校验失败会让请求返回 **500**
   （不是 422，也不是静默跳过）。所以 `status` / `level` / `kind` 这类**暂时**写 `str`
   而不是 `Literal`：库里 `status` 实测有三种值
   （`SELECT status, COUNT(*) FROM comic GROUP BY status` → `连载` 29 / `连载中` 23 / `完结` 2）。
   ⚠️ 待 `comic_core` 补上状态归一 + 存量迁移完成后，才能收紧成 `Literal`。
3. **不得与 `schemas.py`（入参）混放** —— 两者都叫"模型"但职责相反，混在一起会让
   "这个字段到底进还是出"变得要靠猜。

## 命名约定

字段名一律**驼峰**，与前端契约逐字一致（`latestChapterTitle`），不做别名转换 ——
`serializers` 负责把库的蛇形列名映射到这里。
"""
from __future__ import annotations

from datetime import datetime
from typing import Annotated, Generic, TypeVar

from pydantic import BaseModel, BeforeValidator

T = TypeVar("T")


def _to_iso(value: object) -> object:
    """`datetime` → ISO 字符串；其余原样交给 Pydantic 继续校验。

    用**不带参数**的 `isoformat()`（保留微秒），与 FastAPI 原生 `jsonable_encoder`
    对 datetime 的处理一致 —— 换成正则化的 `timespec="seconds"` 会悄悄改掉响应值。
    """
    if isinstance(value, datetime):
        return value.isoformat()
    return value


#: 时间字段统一用它。为什么不能直接写 `str`：service 层有时给 `datetime`、有时给字符串
#: （实测 `sources.meta()` 的 `lastSync` 就是 datetime），而 Pydantic v2 **不做**
#: 字符串的隐式转换 —— 写 `str` 会在前一种情况下校验失败，把接口变成 **500**。
TimeStr = Annotated[str, BeforeValidator(_to_iso)]


# ============================ 信封与分页 ============================


class ApiEnvelope(BaseModel, Generic[T]):
    """统一成功响应包 —— 对应 `core/responses.ok()` 的 `{code, message, data}`。

    失败**不走这里**：错误统一由 `HTTPException` 输出成 `{"detail": ...}`
    （前端 `request.ts` 因此要认两种形状，见那里注释）。
    """

    code: int
    message: str
    data: T


class PageResult(BaseModel, Generic[T]):
    """分页壳 —— 全站统一。

    前端原有 5 份形状相同的 DTO（`CommentPage` / `AdminComicPage` / `AdminUserPage` /
    `LogQueryResult` / `PageResult`）都并入它；只有评论多一个 `enabled`
    （见 `CommentPageOut` —— 前端要能区分「还没人评论」与「评论区已关闭」）。
    """

    items: list[T]
    total: int
    page: int
    pageSize: int


# ============================ 内容（公开浏览） ============================


class HealthOut(BaseModel):
    """`GET /api/health` —— 首页页脚据此标注数据来源是否可达。"""

    comics: int
    chapters: int
    pages: int
    views: int
    categories: int


class CategoryOut(BaseModel):
    """分类标签及其作品数（首项恒为「全部」）。"""

    name: str
    count: int


class ComicOut(BaseModel):
    """作品契约（**前台**）。字段按来源分三类 —— 与 `comic-front/src/types.ts` 同款标注：

    - **源站原始**：`title` / `author` / `category` / `status` / `description` /
      `latestChapterTitle` / `source` / `tags`（经 adapter 归一后各源一致）
    - **平台派生**：`id` / `chapterCount` / `views` / `favoriteCount` / `heat` / `updatedAt`
    - **组装**：`cover`（由 id 拼 `/api/covers/{id}`，**不外泄图床真实路径**）

    ⚠️ 治理字段（`listed` / `commentEnabled` / `sourceComicId`）**不在这里** ——
    普通用户拿不到、也不需要知道哪部被下架，它们只走 `AdminComicOut`。
    """

    id: int
    title: str
    author: str
    category: str
    status: str  # 规范值见 comic_core/status.py（连载中 / 已完结 / 休载 / 已取消）
    description: str
    cover: str
    latestChapterTitle: str
    chapterCount: int
    views: int
    favoriteCount: int
    heat: int
    updatedAt: str
    source: str
    tags: list[str]


class AdminComicOut(ComicOut):
    """管理台「作品管理」行 = `ComicOut` + 三个**治理字段**。

    `sourceComicId`：「补全章节」按 `(源, 源作品 ID)` 复用「按需导入」精确补章
    （源站搜索可能重名，只有 ID 是精确的）。

    ⚠️ 管理台列表**不注入 `tags`**（注入要多一次批量查询，而列表不显示标签），
    所以那里的 `tags` 恒为空数组 —— 是刻意的，不是丢了。
    """

    listed: bool
    commentEnabled: bool
    sourceComicId: str


class ChapterOut(BaseModel):
    """章节契约。`orderNo` 是入库序号（库列名 `chapter_no`）。

    `isNew` = 属于「最近一批入库」（详情页右上角角标），由
    `services.chapters.mark_latest_batch` 先注入 —— 读不到就当 False，不回退查库。
    """

    id: int
    comicId: int
    title: str
    orderNo: int
    createdAt: str
    isNew: bool


class PageOut(BaseModel):
    """阅读器的一页。

    `imageUrl` 指向 `/api/images/{comicId}/{chapterId}/{pageNo}` —— **不暴露源站地址**，
    真实取图（已转存文件 / 源站穿透 / SVG 占位）由 `services.images` 三级兜底决定。
    """

    pageNo: int
    imageUrl: str
    width: int
    height: int


# ============================ 用户与认证 ============================


class UserOut(BaseModel):
    """用户对外视图 —— **永不包含 `password_hash`**（这是它存在的首要理由）。

    `role` 必须给前端：顶栏「管理」入口与 `/#/admin*` 守卫都靠它判断
    （服务端另有 `require_admin` 兜底，前端那层只是体验）。
    `avatarUrl` 为 `''` = 未上传 → 前端回退「首字母头像」。
    """

    id: int
    username: str
    nickname: str
    role: str
    avatarUrl: str
    createdAt: str


class AdminUserOut(BaseModel):
    """授权页的用户行（管理台视角：含角色与注册时间，不含任何凭据）。"""

    id: int
    username: str
    nickname: str
    role: str
    createdAt: str


class AuthResultOut(BaseModel):
    """登录 / 注册的返回：token + 用户。"""

    token: str
    user: UserOut


# ============================ 评论区 ============================


class CommentOut(BaseModel):
    """一条评论。

    `author` 的兜底**刻意写在后端**（`serializers.to_comment`）：账号已删 = 「已注销用户」，
    这样各页面拿到的是同一份文案，不必各写一遍。
    """

    id: int
    content: str
    author: str
    authorId: str
    createdAt: str


class CommentPageOut(PageResult[CommentOut]):
    """评论列表 = 分页壳 + 开关状态。

    `enabled` = 全站总开关 AND 单作品开关。**关闭时也照样返回列表接口**
    （`enabled=false`、列表为空），而不是 404 —— 详情页要能区分
    「还没有人评论」与「评论区已关闭」。
    """

    enabled: bool


class CommentAddedOut(BaseModel):
    """发表评论的返回：新评论 id。

    前端据此**重拉第一页**（评论最新在前，新那条自然出现在顶部），
    比本地拼一条更稳 —— 作者名等兜底规则只有后端这一份。
    """

    id: int


# ============================ 源站搜索（其他来源） ============================


class SourceSearchItemOut(BaseModel):
    """源站搜索命中的一条（**只读、不写库**）。

    `comicId` 非 `None` = 库内已收录 → 前端显示「已收录，直接打开」，
    否则显示「导入并阅读」。
    ⚠️ 这里 `cover` 是**源站外链**（可能被防盗链拦），与 `ComicOut.cover`
    （本地 `/api/covers/{id}`）语义不同 —— 前端对前者要容错隐藏破图。
    """

    source: str
    sourceComicId: str
    title: str
    author: str
    cover: str
    status: str  # 源站原文，未经归一（各源用词不同）
    latestChapterTitle: str
    tags: list[str]
    comicId: int | None = None


class SourceSearchGroupOut(BaseModel):
    """按源分组的结果（单源失败静默跳过，故数组里可能没有某个源）。"""

    source: str
    items: list[SourceSearchItemOut]


# ============================ 消息中心 ============================


class MessageItemOut(BaseModel):
    """消息中心的一条（`message` 表 + 「正在跑的任务」）。

    ⚠️ 列表里有**两种**条目，靠 `status` 与 `messageId` 区分：

    - **已发生的消息**：`id = "msg-<数字>"`、`messageId` 有值、`status` 为 `done`/`failed`；
    - **正在跑的任务**：`id` = 任务号、`messageId = None`、`status = "running"`
      （**仅管理员及以上**可见，由 `services.messages.feed` 临时并入）。

    标记已读要用 `messageId`（任务条目为 `None`，没有可标记的对象）。
    """

    id: str
    messageId: int | None = None
    kind: str  # sync / transfer / inspect / heal / import / schedule / system / 自定义
    level: str  # info / warn / error
    title: str
    body: str
    params: dict | None = None
    taskId: str
    source: str
    username: str
    minRole: str
    status: str  # running / done / failed
    time: str | None = None
    read: bool


class MessageFeedOut(BaseModel):
    """消息列表 + 未读数（一次拿回，前端轮询只发一个请求）。"""

    items: list[MessageItemOut]
    unread: int


class UnreadOut(BaseModel):
    """未读数（只给角标用）。"""

    unread: int


class ChangedOut(BaseModel):
    """「标记已读」类接口的返回：本次新增的记账行数（0 = 本来已读）。"""

    changed: int


# ============================ 收藏与阅读历史 ============================


class FavoriteStateOut(BaseModel):
    """某部作品当前**是否被我收藏**（`favorited`）—— 详情页的「收藏 / 已收藏」按钮读它。"""

    favorited: bool


class HistoryEntryOut(BaseModel):
    """一条阅读历史（**含对应的作品行**，供书架/续读直接用，免去前端再查一次）。

    作品行由 `db.get_comics_by_ids` 一次批量取回（逐条 `get_comic` 会让接口随历史条数线性变慢）；
    库里已不存在的作品**整条跳过**，不让接口整体失败。

    ⚠️ `readAt` 用 `TimeStr` 归一成 ISO 字符串：存储层给的是 **`datetime` 对象**
    （不是字符串），写 `str` 会在响应校验时直接 **500**（2026-10-13 实测）。
    """

    comicId: int
    chapterId: int
    pageNo: int
    readAt: TimeStr
    chapterTitle: str
    comic: ComicOut


class UserRoleOut(BaseModel):
    """授权结果：被改的用户 id 与新角色。"""

    id: int
    role: str


# ============================ 管理台：内容治理 ============================


class ComicListingOut(BaseModel):
    """上下架结果（下架**只改 `comic.listed`**、不删任何数据，重新上架即恢复）。"""

    id: int
    listed: bool


class ComicCommentSwitchOut(BaseModel):
    """单作品评论开关结果。

    ⚠️ 单作品打开**不等于**能评论 —— 全站总开关关着时照样拦（两者是 AND）。
    """

    id: int
    commentEnabled: bool


class CommentSwitchOut(BaseModel):
    """评论开关状态（单作品与全站总开关**共用**这个形状）。"""

    enabled: bool


# ============================ 管理台：采集运维 ============================


class SourceInfoOut(BaseModel):
    """数据源一行（管理台「采集管理」页的开关列表）。

    `interval` 是增量轮询间隔（秒）；`comicCount` 是库内该源作品数；
    `lastSync` 上次同步完成时间 —— 实测是 `datetime`，故用 `TimeStr`。
    """

    name: str
    enabled: bool
    priority: str  # primary / backup
    interval: int
    comicCount: int
    lastSync: TimeStr | None = None


class SourceToggleOut(BaseModel):
    """开关一个源的结果。"""

    name: str
    enabled: bool


class TaskIdOut(BaseModel):
    """后台任务已派发的返回：前端拿 `taskId` 轮询 `GET /api/admin/tasks/{id}`。"""

    taskId: str


class ScheduleConfigOut(BaseModel):
    """「定时任务」配置（落盘在运行时数据目录 `<data>/schedule.json`）。

    节奏用 **5 段 cron**（`分 时 日 月 周`）；`sources` 留空 = 全部「代码里默认启用」的源
    （定时任务**不看**管理台的源开关 —— 它按"参数即准入"运行）。
    """

    enabled: bool
    cron: str
    action: str  # sync / inspect
    sources: list[str]
    mode: str  # incremental / full
    limit: int | None = None
    since: TimeStr | None = None


class ScheduleStatusOut(BaseModel):
    """「定时任务」配置 + 运行态（配置页每次渲染都读它）。

    `sources` 是**后端算出的本轮实际源**（配置留空时的默认集），未必等于 `config.sources`。
    `executorAlive` / `heartbeatAt` 反映**独立执行器进程**（`comic-scheduler`）的存活 ——
    它不在 api 进程里，所以"在不在"本身就是个要展示的状态。
    """

    config: ScheduleConfigOut
    sources: list[str]
    nextRunAt: TimeStr | None = None
    serverTime: TimeStr
    running: bool
    lastRunAt: TimeStr | None = None
    lastStatus: str | None = None  # running / done / failed
    lastMessage: str | None = None
    lastTaskId: str | None = None
    lastSources: list[str]
    cronError: str | None = None  # 配置文件被手改坏时才有值
    executorAlive: bool
    heartbeatAt: TimeStr | None = None
    executorPid: int | None = None


class ScheduleRunNowOut(BaseModel):
    """「立即执行一次」的返回 —— **只是"请求已提交"**，不是 taskId。

    采集在独立进程里跑，api 拿不到任务号；结果看 `ScheduleStatusOut` 的
    `running` / `lastRunAt` / `lastMessage`，以及任务表（`task_type=schedule`）。
    """

    requested: bool
    requestedAt: TimeStr | None = None
    userId: int | None = None
    username: str = ""


class AdminTaskOut(BaseModel):
    """管理台后台任务（`admin_task` 表）。

    ⚠️ 任务**落库**（2026-10-06 从进程内 dict 搬来）：api 重启不丢、且与**触发账号**绑定
    （`userId`/`username`），所以能看出"这条是谁点的"；定时轮次没有账号，`userId` 为 `None`。

    `result` / `params` 是**自由形状**（各任务类型不同：采集统计、导入结果、入参快照…），
    故声明为 `dict`——这是刻意的，不是偷懒：给它定死结构会让新增任务类型时改不动。
    """

    id: str
    type: str  # sync / transfer / inspect / heal / import / schedule
    status: str  # running / done / failed
    message: str
    result: dict | None = None
    params: dict | None = None
    userId: int | None = None
    username: str
    startedAt: TimeStr
    finishedAt: TimeStr | None = None


class LogRecordOut(BaseModel):
    """运行日志一行（`log_record` 表）。

    日志由 logging Handler 在打日志时自动落库（见 crawler 的 `log_handler`），
    所以这里查到的就是 `api.log` 里那些业务日志，只是**能按条件筛**。
    """

    id: int
    createdAt: TimeStr
    level: str
    logger: str
    message: str
    taskId: str
    taskType: str
    excType: str
    source: str
    comicId: int | None = None
    comicTitle: str
    chapterId: int | None = None
    chapterTitle: str
    endpoint: str
    pages: int | None = None
    reason: str
    event: str
    #: 只有**详情**接口带堆栈全文（列表接口不带，免得一次拉回几十条大字段）
    excText: str | None = None


class LogOptionsOut(BaseModel):
    """日志查询页的筛选候选值（级别 / 事件类型）。"""

    levels: list[str]
    events: list[str]


class PurgeOut(BaseModel):
    """清理日志的结果：删除条数。"""

    deleted: int
