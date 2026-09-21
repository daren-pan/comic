---
name: 新增爬虫源
description: >-
  新增漫画爬虫源的完整接入流程。当用户要"加一个新源/接入新站点/添加爬虫源"
  时触发。覆盖：建子包、写 adapter、注册、声明能力、写 README、验证。
  契约见 sources/base.py，最完整参考实现见 sources/zaimanhua/。
when_to_use: >-
  命中任一即触发：
  (a) "接入一个新源/新站点/新漫画站"；
  (b) "加一个爬虫源""新增源站""添加采集源""加个新的爬虫"；
  (c) 要复制现有源结构做新源适配器；
  (d) 问"怎么加源""接入源站要改哪些文件"。
version: 1.1.0
---

# 新增爬虫源

源站层契约在外（`base.py`/`registry.py`），各源自包含子包在里。
**新增一个源 = 复制一个子包 + 在聚合处加一行**，不改 `config.py` 或解析逻辑。

## 文件结构（4 件套）

```
crawler-service/src/comic_crawler/sources/{源名}/
├── __init__.py    # 导出 Adapter + 声明 SOURCES（频率/启停就近维护）
├── adapter.py     # CrawlerAdapter 实现（列表/详情/章节图）
├── README.md      # 接口路径·请求头·分页·限流·已知坑
└── fixtures/      # 样例响应（可选，离线测试用）
```

## 接入步骤

### 1. 建 adapter.py

```python
from __future__ import annotations
import httpx
from ...models import ChapterBrief, ComicBrief, ComicDetail, ComicListResult, PageInfo
from ..base import CrawlerAdapter
from ..registry import register

@register("源名")  # ← 注册进 registry，调度器用 create_adapter("源名") 拿实例
class XxxAdapter(CrawlerAdapter):
    source_name = "源名"
    base_url = "https://..."
    robots_allowed = True
    capabilities = {"search", "ref"}   # 支持搜索 + 解析链接/ID；都不支持就 set()
    image_hosts = {"img.example.com"}  # 图床域名白名单（防 SSRF）；图床=站点同域可省

    # --- 三个必须实现的抽象方法 ---
    def fetch_comic_list(self, page=1, since=None) -> ComicListResult: ...
    def fetch_comic_detail(self, comic: ComicBrief) -> ComicDetail: ...
    def fetch_chapter_pages(self, detail, chapter) -> list[PageInfo]: ...

    # --- 可选覆盖（按需）---
    # def pre_fetch(self): ...           # 生命周期：抓取前初始化
    # def post_fetch(self): ...          # 生命周期：抓取后清理
    # def search_comics(self, keyword, limit=20) -> list[ComicBrief]: ...  # capabilities 含 "search" 才有意义
    # def parse_comic_ref(self, ref) -> str | None: ...                    # capabilities 含 "ref"
    # def fetch_source_page_urls(self, cid, chid) -> list[str] | None: ... # sign 短时效源才需（重签）
```

⚠️ `HttpFetcher.get()` 只支持桌面 UA + text（无 JSON/自定义头）→ **适配器内自建 `httpx.Client`**（参考 zaimanhua 的 `_api_get`：带重试、自定义 headers、`timeout=12`）。

### 2. 建 __init__.py

```python
from ...config import SourceConfig
from .adapter import XxxAdapter

SOURCES = [
    SourceConfig(
        name="源名",
        priority="primary",            # primary / backup
        crawl_interval_seconds=3600,   # 增量轮询间隔（秒）
    ),
]

__all__ = ["XxxAdapter", "SOURCES"]
```

`SourceConfig` 字段（`config.py`）：`name`、`base_url`、`priority`、`crawl_interval_seconds`、`full_sync_cron`、`enabled`。

### 3. 在 sources/__init__.py 注册聚合

```python
from . import xxx  # 触发 @register 注册 + 带入 SOURCES 配置
_SOURCE_PACKAGES = (zaimanhua, mangadex, weebcentral, xxx)  # 顺序 = 轮询/展示顺序
```

只需改这两行。`SOURCES` 列表会自动聚合所有子包的配置。

### 4. 写 README.md

记录：接口路径 · 请求头 · 分页方式 · 限流策略 · 已知坑（字段名差异、签名时效、语言选择…）。参考 `sources/zaimanhua/README.md`。改动同一提交内更新。

### 5. 验证

```
scripts/check.sh        # crawler 单测 + api 分层守卫 + tsc --noEmit
# 管理台 /#/admin → /api/admin/sources 应出现新源
# 抽一部作品确认 列表/详情/章节图 都能取到
```

## 硬约束（必须遵守）

| # | 约束 | 原因 |
|---|---|---|
| 1 | `image_hosts` 必须列出图床域名 | 转存/穿透取图的白名单，防 SSRF；图床 ≠ 站点域的源必须补 |
| 2 | 详情逐章 `canRead` 不可信 | 实测 131 章全 false 但实际可读；能否读由 `ondemand._probe_readable` 实测探测 |
| 3 | `restricted` 只认 `is_lock` | 不用详情逐章 canRead 判 |
| 4 | **判重只看 `(源, 源作品 ID)`** | 跨源**不合并**（用户 2026-09-16 决策）：同一部作品在别的源收过是**另一行**，各记各自章节进度（不同译本进度往往不同）。适配器不需要做任何跨源去重或语言归一 |
| 5 | 时间列一律 DATETIME | 写入 `_now()`，`_as_dt()` 归一 ISO 串 |
| 6 | 新漫画首采收**全部章节目录**（`FIRST_CHAPTERS=None`） | 页面仍只登记 source_url 懒下载；只收最新一话会导致旧章节看不到（章节行缺失）。增量只补更新的章节 |
| 7 | 不保存章节页数 | 源站无批量途径，逐话太慢被软限流；chapter 无页数列、API 不返回 pageCount |

## 参考实现（按完整度排序）

| 源 | 特点 | 重点参考点 |
|---|---|---|
| **zaimanhua**（主源） | H5 API、sign 短时效签名 | 最完整：搜索/详情/章节/重签/引用解析全有；`_row_to_brief(id_field=)` 处理列表 vs 搜索 ID 字段差异 |
| **mangadex** | v5 REST API | external 外链坑：zh/en 章节常是外链被 `includeExternalUrl=0` 排除 → `_pick_langs()` 为 zh → en → 其它可用语言（命中即停） |
| **weebcentral** | HTML 搜索 | URL 永久有效，无需覆写 `fetch_source_page_urls`；`.png` 实为 JPEG |
| **copymanga** | 公开 JSON API（前后端分离） | 成功码看 body 的 `code`（HTTP 可能是非标 210）；作品 ID 是 `path_word` 字符串；`groups` 在 results 层级、字段名 `path_word`；分片图床用 `image_hosts = {"*.域名"}` 通配 |

## 常见坑速查

- **搜索 vs 列表的 ID 字段名不同**：zaimanhua 列表用 `comic_id`（`id` 恒为 0），搜索用 `id` —— 用 `id_field` 参数区分，别写死。
- **mangadex 列表字段不能当更新时间**：`latestUploadedChapter` 是 UUID，要逐部 `/chapter?manga={id}&order[publishAt]=desc&limit=1`。
- **zaimanhua 章节图 sign+t 短时效**：采集入库的 URL 数日即过期 → `fetch_source_page_urls` 现场重签 + 实例级缓存（同章多页一批只请求一次）。
- **源站接口偶发返回空**：判定"有无数据/能否读"必须多次采样或换时刻复测，不归因（分不清缺数据与需付费），只按"能否取到图"处理。
- **繁体源（zh-hant）照原样透出即可，不要自己转简体**：作品判重**刻意不做繁简折叠**（繁体/简体是
  两个译本、进度往往不同 → 各占一行，见硬约束 4），所以标题保持源站原文；只有**标签归一**那层
  才会折叠繁简（`taxonomy` 的 `zhconv`，`格鬥`→`格斗`→「动作」），与适配器无关。
  `Accept-Language` 之类的语言头只改界面文案、通常**不改作品名**，别指望它。
  源站若有别名/原名/多语言标题字段（copymanga `alias`、zaimanhua `realName`/`aliasName`、
  mangadex `altTitles`），当前**不采集**（多语言统一方案已搁置）。
