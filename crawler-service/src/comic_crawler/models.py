"""领域数据模型定义。

这些模型与源站无关：任何源站适配器解析完成后，都统一输出
本模块中的结构，由流水线（去重 → 入库 → 刷新索引）消费，
从而保证「新增源站不改业务代码」。

模型层级对应架构方案 §3：comic 作品 → chapter 章节 → page 分页。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime


@dataclass(slots=True)
class ComicBrief:
    """列表页中的漫画摘要（增量轮询 / 全量扫描的输入单元）。"""

    source: str                # 源站标识，对应 source 表的 name
    source_comic_id: str       # 源站内作品 ID（去重键之一）
    title: str                 # 标题（原始写法，归一化在指纹层完成）
    author: str = ""
    cover_url: str = ""
    status: str = "连载"        # 连载 / 完结
    category: str = ""         # 题材分类，如 "热血 · 冒险"
    latest_chapter_title: str = ""   # 列表页可见的"更新至第 X 话"
    detail_url: str = ""       # 详情页地址，由列表页解析得出
    fetched_at: datetime = field(default_factory=datetime.now)


@dataclass(slots=True)
class ChapterBrief:
    """章节摘要（详情页解析结果）。"""

    source: str
    source_comic_id: str
    chapter_no: int            # 章节序号，comic_id + chapter_no 联合唯一
    title: str
    source_chapter_id: str     # 源站内章节 ID（去重/更新检测用）
    pages_url: str = ""        # 章节图片页地址


@dataclass(slots=True)
class PageInfo:
    """章节内的一页图片。"""

    page_no: int
    source_url: str            # 源站原图地址
    oss_url: str = ""          # 转存后地址（由图片服务回填）
    cached_status: str = "未转存"  # 未转存 / 已转存 / 失效


@dataclass(slots=True)
class ComicDetail(ComicBrief):
    """漫画详情（含简介与章节列表）。"""

    description: str = ""
    chapters: list[ChapterBrief] = field(default_factory=list)


@dataclass(slots=True)
class ComicListResult:
    """列表页抓取结果：漫画摘要列表 + 分页信息。"""

    items: list[ComicBrief]
    page: int
    has_next: bool = False


@dataclass(slots=True)
class SyncStats:
    """一次同步任务的统计结果。"""

    source: str
    mode: str = "incremental"
    started_at: str = ""   # ISO 时间，由调度器写入
    total_seen: int = 0
    new_comics: int = 0
    updated_comics: int = 0
    new_chapters: int = 0
    failed: int = 0

    def summary(self) -> str:
        return (
            f"[{self.source}::{self.mode}] 扫描 {self.total_seen} 部 | "
            f"新增 {self.new_comics} | 更新 {self.updated_comics} | "
            f"新增章节 {self.new_chapters} | 失败 {self.failed}"
        )
