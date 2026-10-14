"""领域对象序列化：数据库蛇形字段 → 前端驼峰契约（**构造 `schemas_out` 的响应模型**）。

⚠️ **2026-10-13 起返回类型由 `dict` 改为 Pydantic 模型**（形状的声明搬去 `schemas_out.py`）。
转换逻辑一字未变，只做两件事：① 返回值换成模型实例；② 把原先散在这里的
`int()` / `or ""` 兜底补齐（`chapterCount` 此前漏套 `int()`，见下）。
好处是路由能声明 `response_model` → OpenAPI 有响应结构 → 前端类型可自动生成；
代价是**模型必须与这里构造的字段一一对应**，守卫见 `tests/test_response_contract.py`。

这一层**只做形状转换、不碰存储**（2026-09-24 起）：模块**不导入 `core.db`**，
因此任何 import 它的地方都能保持"纯逻辑、不连库"，单测不必再装存储桩。

唯一需要外部数据的字段是作品标签（在 `comic_tag` 关联表里、不在 `comic` 行上）——
由调用方**先注入 `row["tags"]`** 再交给 `to_comic`：

- **列表接口**：`services.tags.attach_tags(rows)`（一条 SQL 批量注入，避免逐条查询）；
- **单条接口**（详情）：`services.tags.attach_tags([row])`，代价可忽略。

`to_comic` 读不到 `tags` 时按空数组处理、**不回退查库** —— 忘了注入会表现为
"标签为空"，新增调用点时请照抄上面两种写法。

⚠️ 作品**来源是单个**（`source`，不是数组）：一行只属于一个源。判重只看
`(source, source_comic_id)` —— 同一部作品在别的源收过**是另一行**（跨源不合并，
见 `storage/mysql/comic_store.upsert_comic`），所以同名作品可能在列表里出现两次，
各自带自己的来源与章节进度。

⚠️ **三个派生列不是 `comic` 表的列**：`chapter_count` / `favorite_count` / `heat` 由
`comic_store._COMIC_COLS` 在 SQL 里聚合/算出（实测 `SELECT favorite_count FROM comic`
会报 `Unknown column`）—— 调用方的查询必须照抄 `_COMIC_COLS` 的投影，
否则 `to_comic` 会 `KeyError`。这是**刻意**的 fail-fast：静默给 0 会让榜单排序错乱而无人察觉。
"""
from __future__ import annotations

from datetime import datetime

from comic_core.status import normalize_status
from schemas_out import (
    AdminComicOut,
    AdminUserOut,
    ChapterOut,
    ComicOut,
    CommentOut,
    PageOut,
    UserOut,
)


def _iso(value: object) -> str:
    """时间 → 前端好解析的 ISO 字符串（`T` 分隔、秒精度）。

    与 `services/messages._iso` 同款：驱动可能给 `datetime` 也可能给字符串，
    字符串还要防着"空格分隔"的形式被丢给 JS 的 `new Date()` 去猜时区。
    """
    if value is None:
        return ""
    if isinstance(value, datetime):
        return value.isoformat(timespec="seconds")
    return str(value).strip().replace(" ", "T")


def to_comic(row: dict) -> ComicOut:
    """库行 → `ComicOut`（前台作品契约）。"""
    # ⚠️ 这里曾用白名单静默兜底（`status if status in ("连载中","已完结") else "连载中"`），
    # 于是库中 2 部已完结的作品被强制显示成"连载中"（54 行里 31 行不在白名单内）。
    # 现在改调**唯一**的归一函数：认不出的写法原样保留，不再吞值（2026-10-13）。
    status = normalize_status(row.get("status"))
    tags = list(row.get("tags") or [])     # 由调用方注入（见模块头）；未注入即空数组
    return ComicOut(
        id=int(row["id"]),
        title=row["title"] or "",
        author=row["author"] or "",
        category=row["category"] or "",
        status=status,
        description=row["description"] or "",
        cover=f"/api/covers/{row['id']}",
        latestChapterTitle=row["latest_chapter_title"] or "",
        # ⚠️ 必须 int()：库行的值类型**没有保证**（同一句 SQL，用 MCP 工具查是字符串
        # `"30"`，项目自己的存储层跑出来是 int）—— 这里曾漏套，靠驱动好心才没出事。
        chapterCount=int(row.get("chapter_count") or 0),
        views=int(row.get("views") or 0),               # 累计浏览次数（原始计数）
        favoriteCount=int(row.get("favorite_count") or 0),
        heat=int(row["heat"]),                          # 热度分：1000 + 浏览 + 2×收藏
        updatedAt=_iso(row["sync_time"]),
        source=row.get("source") or "unknown",          # 该行来自哪个源（一行=一个源）
        tags=[str(t) for t in tags],
    )


def to_chapter(row: dict) -> ChapterOut:
    """章节行 → `ChapterOut`。

    `isNew`：是否属于「最近一批入库」（详情页右上角角标）—— 由调用方先注入
    `row["is_new"]`（`services.chapters.mark_latest_batch`），与 `tags` 同一约定：
    **读不到就当 False，不回退查库**。
    """
    return ChapterOut(
        id=int(row["id"]),
        comicId=int(row["comic_id"]),
        title=row["title"] or "",
        orderNo=int(row["chapter_no"]),
        createdAt=_iso(row["sync_time"]),
        isNew=bool(row.get("is_new")),
    )


def to_admin_comic(row: dict) -> AdminComicOut:
    """管理台「作品管理」行的契约：在 `to_comic` 之上补三个**治理字段**。

    `listed`（上架状态）/ `commentEnabled`（单作品评论开关）/ `sourceComicId`（源站作品 ID）
    **只给管理台** —— 前台契约（`to_comic`）不带它们：普通用户拿不到、也不需要知道哪部被下架了。
    `sourceComicId`：「补全章节」按 `(源, 源作品 ID)` 复用「按需导入」`POST /api/admin/import`
    精确补章（源站搜索可能重名，只有 ID 是精确的）。

    `to_comic` 需要调用方先注入 `tags`；管理台列表不显示标签，所以这里**不注入**
    （省一条批量查询），`tags` 出来是空数组。
    """
    return AdminComicOut(
        **to_comic(row).model_dump(),
        listed=bool(int(row.get("listed") or 0)),
        commentEnabled=bool(int(row.get("comment_enabled") or 0)),
        sourceComicId=str(row.get("source_comic_id") or ""),
    )


def to_comment(row: dict) -> CommentOut:
    """评论行 → 前端契约。

    作者名取 `nickname`、空则退回 `username`；**两者都空 = 账号已被删**
    （读取侧是 `LEFT JOIN user`，没命中就是 NULL）→ 显示「已注销用户」。
    这句兜底**刻意写在后端**：各页面拿到的是同一份文案，不必各写一遍。

    `createdAt` 给 ISO 字符串（与 `to_chapter.createdAt` 同一处理），前端自己格式化。
    """
    name = (row.get("nickname") or "").strip() or (row.get("username") or "").strip()
    return CommentOut(
        id=int(row["id"]),
        content=row["content"] or "",
        author=name or "已注销用户",
        authorId=str(row.get("user_id") or ""),
        createdAt=_iso(row["created_at"]),
    )


def to_page(row: dict, comic_id: int, chapter_id: int) -> PageOut:
    """页行 → 前端契约。

    `imageUrl` 指向本项目自己的取图端点（**不暴露源站地址**）；
    `width` / `height` 目前是固定占位（源站大多不给每页尺寸），前端按它预留位置避免跳动。
    """
    return PageOut(
        pageNo=int(row["page_no"]),
        imageUrl=f"/api/images/{comic_id}/{chapter_id}/{row['page_no']}",
        width=720,
        height=1020,
    )


def user_out(user) -> UserOut:
    """用户对外视图（隐藏 password_hash）。

    `role` 必须给前端：顶栏「管理」入口、`/#/admin*` 路由守卫都靠它判断
    （服务端另有 `require_admin` 兜底，前端这层只是体验）。
    """
    return UserOut(
        id=int(user["id"]),
        username=user["username"] or "",
        nickname=user["nickname"] or user["username"] or "",
        role=user.get("role") or "user",
        # 头像 URL（'' = 未上传 → 前端回退「首字母头像」）；上传/清空见 routers/auth.py
        avatarUrl=user.get("avatar_url") or "",
        createdAt=_iso(user["created_at"]),
    )


def to_admin_user(row) -> AdminUserOut:
    """授权页的用户行（管理台视角：含角色与注册时间，不含任何凭据）。"""
    return AdminUserOut(
        id=int(row["id"]),
        username=row["username"] or "",
        nickname=row["nickname"] or row["username"] or "",
        role=row.get("role") or "user",
        createdAt=_iso(row["created_at"]),
    )
