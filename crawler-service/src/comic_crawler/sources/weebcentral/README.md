# Weeb Central 源站说明（weebcentral_source.py）

## 目标站
- 站名：Weeb Central（weebcentral.com）
- 性质：英文漫画/韩漫聚合站（含官方授权连载 `official.lowee.us` 与扫描组分发 `scans.lastation.us`）
- 合规状态：**学习用途 · 受控样本**（config.py `priority=backup` + 低频 3600s；单部少量章节、不发布、可按 `source=weebcentral` 清理）
- 逆向结论：纯服务端渲染 + htmx 局部刷新，**匿名即可读**，无登录、无签名、无付费/VIP 门禁
- 能力：列表 / 详情 / 章节图 + **关键词搜索**（`/search/data`，见 §⑤）+ 作品链接/ULID 解析，支持按需导入

## 关键机制（2026-09-09 实测确认）

### ① 列表 = 首页「最近更新」区（约 32 部，无分页）
`GET https://weebcentral.com/` 的 `<!-- Latest Updates -->` 区块（`<section class="bg-base-200...">`）内 `<article>` 卡片：
- 标题：`<div class="flex-1 truncate font-semibold text-lg">`（或 `data-tip`）
- 系列链接：`/series/{ulid}/{slug}`（**ulid 即 source_comic_id**）
- 章节链接：`/chapters/{uuid}`（即该部最近更新的那话）
- 章节标签：`<span>Chapter N</span>` / `Episode N` / `S2 - Episode 1` / `Volume 34`（不固定）
- 时间：`<time class="text-datetime" datetime="ISO">`（**精确到秒**，如 `2026-09-09T01:53:27.539Z`）→ 增量窗口时间基准
- 封面：`https://temp.compsci88.com/cover/fallback/{ulid}.jpg`（normal/small 有 webp）
- ⚠️ 首页「最近更新」区**无分页**（`/updates`、`/latest`、`/?page=2` 均无效）→ `has_next` 恒为 `False`

### ② 系列详情 = `/series/{ulid}/{slug}`
元数据在 `<li><strong>Label: </strong>…</li>` 列表里：
- 标题：`og:title`（`{title} | Weeb Central`，需去掉后缀）
- 作者：`Author(s): <a href="/search?author=...">`（可多个）
- 状态：`Status: <a>Ongoing</a>` → `连载`/`完结`/`休载`/`已取消`
- 标签：`Tags(s): <a href="/search?included_tag=...">`（genre）
- 描述 / 封面：`og:description` / `og:image`

### ③ 全章节列表 = `/series/{ulid}/full-chapter-list`（htmx 端点）
- **纯 GET 即可**（无需 `HX-Request` 头），返回**全部章节**（Eleceed 417 条）
- 每条：`<a href="/chapters/{uuid}">`，章节标题是 `grow` 容器内**第一个 `<span>`**（后续 span 是 "Last Read"/新章节指示器，取 `string()` 会带出 "Last Read"，须只取第一个 span）
- 每章还带 `<time datetime="ISO">`（章节更新时间，精确到秒）
- 顺序：**新 → 旧**（最新话在前），与调度器 `detail.chapters` 约定一致

### ④ 章节图片 = `/chapters/{uuid}/images?is_prev=False`（htmx 端点）
- ⚠️ **章节页首屏 HTML 只含第一张图**，其余由 Alpine.js `singlePageNavigation` 组件在 `init()` 里发这个 htmx 请求懒加载（页内内嵌 `max_page: parseInt('42')`）——适配器**必须直接请求 `/images` 端点**而非解析首屏
- 纯 GET 即可（无需 `HX-Request` 头），返回 `<section id="chapter-images">` 片段，内含**完整** `<img>` 列表
- ⚠️ **图床域名不固定**：`scans.lastation.us`（扫描组）与 `official.lowee.us`（官方授权）等，须匹配所有 `//img[starts-with(@src,'http')]` 而非固定某域
- ⚠️ 图床 `.png` 扩展名但实际字节可能是 **JPEG**（magic `ffd8ffe0`）——项目 `_read_image_file` 按魔数判类型，不受影响，但适配器不能靠扩展名判格式
- 图床 URL **永久有效、无 Referer/签名限制** → **无需覆写 `fetch_source_page_urls`**（base 默认返回 None）

### ⑤ 搜索（2026-09-12 启用，用于搜索页「其他来源」与按需导入）

**用 `GET /search/data?text=<关键词>&display_mode=Full Display`**（纯 GET，无需 HX-Request 头）。
端点取自 `/search` 页「高级搜索」表单的 `hx-get`（该表单只有 `text` / `author` / `display_mode` 三个字段）。

⚠️ **不要用 `/search/simple`**：那是输入框的「快速搜索」下拉提示（`hx-post` + `hx-trigger="input changed delay:500ms"`），
只返回极少条 —— 实测 `eleceed` 仅 1 条，`/search/data` 才是完整结果集。

**结果卡片**（`<article class="bg-base-300 …">`，桌面版 + 移动版各一份封面/标题）：
- 系列链接：`/series/{ulid}/{slug}`（**ULID = source_comic_id**）
- 标题：`.//div[contains(@class,'line-clamp')]`（兜底 `text-ellipsis`，再兜底封面 `img@alt` 去 " cover"）
- 作者：`<strong>Author(s): </strong>` 后的 `<a>`（可多个）；状态：`Status:` 后的 `<span>`
- 标签：`<strong>Tag(s): </strong>` 后的多个 `<span>`（**detail 页写作 `Tags(s)`**，故 XPath 用 `contains(text(),'Tag')` 兼容两者）
- 封面：`https://temp.compsci88.com/cover/fallback/{ulid}.jpg`

⚠️ **搜索卡片不含「最新章节 / 更新时间」**（只有 标题/封面/作者/状态/标签），故 `search_comics`
返回的 `latest_chapter_title` 与 `source_updated_at` 留空 —— 这两个字段由详情接口补齐，不影响导入。

**按需导入支持**：`capabilities = {"search", "ref"}`。
- `parse_comic_ref`：接受纯 ULID（大小写皆可，统一大写）与 `/series/{ulid}/{slug}` 链接；**外站链接直接拒绝**。
- `fetch_comic_detail` **不再依赖 `comic.detail_url`**（搜索命中/按需导入只给 ULID 时它是空的）——
  缺链接时自行拼 `{BASE}/series/{ulid}`（站点不带 slug 也能打开），实测可正常取到 417 章完整目录。

⚠️ **刻意不声明 `image_hosts`**：图床域名不固定（`scans.lastation.us` 扫描组 / `official.lowee.us` 官方授权 /
`temp.compsci88.com` 封面 等），白名单写不全反而会让读时穿透取图被 `_host_allowed` 拒掉。
故沿用「库内数据可信」的既有约定（与 mangadex 一致；zaimanhua 因图床固定才声明）。

## 模型映射
| 源站对象 | 模型 | 说明 |
|---|---|---|
| 1 部系列（series ULID） | `comic` 表 | `source_comic_id` = 系列 ULID |
| `full-chapter-list` 每个 `/chapters/{uuid}` | `chapter` 表 | `chapter_no` 从标题 `Chapter N`/`Episode N` 解析（`S2 - Episode 1`→1、`Ch 5.5`→55 放大 10 倍、无编号用 10000+ 高位兜底） |
| `/images` 里每个 `<img src>` | `page` 表 | `source_url` 指向 CDN 原图 |

## 时间窗口（增量）说明
- 列表时间基准 = 卡片 `<time datetime="ISO">`（该部最近一次更新的章节时间，精确到秒）
- 首页「最近更新」区只显示最新的约 32 部（无分页）——增量窗口覆盖「最近 32 部更新」，若窗口内更新量超过该区上限会漏掉更早的更新（学习用途受控样本可接受）
- **受控样本（仅测试）**：可用 `cli run --source weebcentral --limit 1` 临时只抓最近 1 部（勿写死为默认值）
- `since` 为 naive（本机时间）时经 `_utc` 归一为 aware UTC 再与卡片 ISO 时间比较（同 mangadex 的处理）

## 页面转存约定（懒转存）
- **页面图一律懒转存**：调度器 `_upsert_detail` 入库只登记源站 URL（`cached_status=未转存`），图片字节**不主动下载**，由失效巡检 `lazy_transfer` 或用户阅读访问时按需转存（见 `image_service.lazy_transfer`）
- 封面 `cover_url` **入库即落盘**（`ensure_cover_local` → `covers/{id}.jpg`），非懒转存（保证 API 有封面可显示）
- Weeb Central 图床 URL 永久有效、无签名 → `_url_expired` 恒 `False`，懒转存直接按登记 URL 下载，**无需覆写 `fetch_source_page_urls`**（base 默认返回 None）

## 受控参数（改大即扩大收录，务必确认仍属受限样本）
| 常量 | 默认 | 说明 |
|---|---|---|
| `MAX_ITEMS` | 60 | 单次列表最多收录条数（首页最近更新区约 32 部，留余量）；**仅测试**可经 `cli run --source weebcentral --limit 1` 临时只抓 1 部 |
| `MAX_CHAPTERS` | 2000 | 单部最多收录章节数（防极端长连载失控；新漫画首采由调度器 `FIRST_CHAPTERS=1` 再收紧为最新 1 话） |
