# guazi 瓜子漫画 适配器接口说明

> 目标站：`https://www.guazimanhua.com`
> 适配器源码：`crawler-service/src/comic_crawler/adapter/guazi_source.py`
> 本文件为**持久化参考**，记录接口与解析要点，避免每次重新探测。

## 1. 站点概况

- 典型中文漫画站：**PHP 服务端渲染**（SSR），HTML 直接返回，无 JSON API
- 多部漫画按「最近更新」排序
- `robots.txt` 仅屏蔽 AI 爬虫（GPTBot/ClaudeBot 等），普通 UA 抓取不受限
- 图片走 CDN：`img.guazicdn.com`，**无防盗链**，可直接下载

## 2. 请求方式

- 走通用 `HttpFetcher`（桌面 UA 池，返回 HTML 文本）
- 用 `parsel.Selector` 做 XPath 解析
- **无需**自定义头（不像 zauimanhua 需要 `Platform: h5`）
- 页面地址：`{BASE}/comic.php?id={comic_id}` / `{BASE}/chapter.php?id={chapter_id}`
  其中 `BASE = https://www.guazimanhua.com`

## 3. 接口/页面清单

### 3.1 列表页（「最近更新」榜，按时间范围）

```
GET /update.php?date={today|yesterday|week|month|all}&page={page}
```

- 列表入口为**更新榜** `update.php`（不是首页 `/`，首页只剩前 N 部会漏）
- `date` 参数是站点固定档位：`all` / `today` / `yesterday` / `week` / `month`，**无自定义区间**
- 每页 30 部，可翻页；卡片结构 `//article[contains(@class,'mobile-update-card')]`
- 目标区块：`//article[contains(@class,'mobile-update-card')]`
- 每张卡片取：
  - 作品ID：`comic.php?id=(\d+)`（从 `<h2><a>` 的 href 提取）
  - 标题：`.//h2/a` 文本
  - 封面：`.//img[contains(@class,'cover') or contains(@class,'mobile-update-cover')]/@src`
  - 分类：`.//small` 文本
  - 最新章节名：`.//p/a` 文本
- **卡片上无时间戳**（这是与再漫画的关键差异）——只有标题/最新章节/状态
- 翻页探测：`_next_page_has_items()` 直接抓下一页数卡片，而非依赖「下一页链接」
  （当天不足一页时链接仍存在但第 2 页为空，避免误判）
- 受控参数：`MAX_PAGES = 5`（最多扫描页数，每页 30 部，防失控）

### 3.1.1 时间窗口增量（方案A · 按天）

瓜子**没有秒级时间戳**，详情页 `<p class="desc">` 里有「更新时间：YYYY-MM-DD」精确到日，
故增量窗口粒度只能是「日」。实现分两类：

1. **首次（`since=None`）**：`date=today` 全量抓当天更新的所有漫画，**不额外请求详情页**。
2. **之后增量（`since` 非空）**：
   - 把 `since` 对齐到日 `since_day`，按 `today - since_day` 天数差选 `date` 档位
     （撑大窗口保证不漏）：`<=1天→today`、`<=6天→week`、`<=31天→month`、`>31天→all`
   - 再对每部进详情页解析「更新时间」，仅保留 `updated_date >= since_day` 的
     （把撑大的窗口砍回精确到日的区间），见 `_passes_window` / `_extract_update_date`

> 代价：since 非空时每部多一次详情页请求拿时间。为省流量，**首次不过滤（不额外请求）**。

### 3.2 详情页

```
GET /comic.php?id={comic_id}   （即 comic.detail_url）
```

- 简介：`//*[contains(@class,'mobile-comic-desc')]`
- 分类：`//*[contains(@class,'mobile-comic-tags')]`
- 状态：全文查找 `状态为(连载|完结)` 正则
- **章节列表**（新 → 旧）：优先取 `//*[@data-chapter-list]/a[contains(@href,'chapter.php?id=')]`
  （即「全部章节」容器）；无则兜底取所有 `chapter.php?id=` 链接
- 章节ID：`chapter.php?id=(\d+)`
- 受控参数：`MAX_CHAPTERS = 3`（每部仅收主线最新 N 话）

**章节筛选逻辑**：
- 功能链接过滤：`BANNED_TEXTS = ("开始阅读", "去阅读", "最新更新")`
- 主线和番外分流：主节点（标题非 `[番外]` 开头）优先取前 `MAX_CHAPTERS`；番外仅作补充
- 防止「最新更新恰为番外」时整部收录的都是花絮

### 3.3 章节页（正文图）

```
GET /chapter.php?id={chapter_id}   （即 chapter.pages_url）
```

- 正文图：`//img[contains(@src,'guazicdn.com')][contains(@src,'/chapters/')]/@src`
- 图片为 CDN 原图，按顺序即为页序

## 4. 章节号（chapter_no）取 key

- `第48话` → 48（`CN_NUM_RE = 第\s*(\d+)\s*话`）
- 无「第N话」的纯数字 → 取首个数字（`PLAIN_NUM_RE = (\d+)`）
- `[番外]` / 无数字章节 → `10000 + idx`（**高位防冲突**，番外不与主线撞号，且排在大号区最前）

## 5. 受控参数（学习用途 · 受控样本）

```python
MAX_PAGES = 5     # 更新榜最多扫描页数（每页 30 部，防失控；当日更新超出则截断）
MAX_CHAPTERS = 3  # 每部仅收录主线最新 N 话
BANNED_TEXTS = ("开始阅读", "去阅读", "最新更新")   # 章节列表功能链接
```

> 历史：早期曾用 `MAX_COMICS = 4` 取首页「最近更新」前 N 部，因只取前几部会漏，
> 已弃用，改为 `update.php` 更新榜翻页（`MAX_PAGES`）。

## 5.1 时间窗口相关方法（方案A · 按天）

- `_since_day(since)`：把 `since`（秒级 datetime）截到日，`None`=首次不过滤
- `_date_param(since_day)`：按天数差映射 `date` 档位（today/week/month/all）
- `_passes_window(brief, since_day)`：进详情页解析「更新时间」并判断 `>= since_day`；
  详情页异常或取不到时间时**放行**（不误漏，靠 upsert 幂等兜底）
- `_extract_update_date(sel)`：正则 `更新时间[：:]\s*(\d{4}-\d{2}-\d{2})` 解析 `<p class="desc">`

## 6. 模型映射

- 1 部漫画（comic_id）→ comic 表 1 条
- 每个章节入口 → chapter 表 1 条（`chapter_no` 见 §4）
- 每张正文图 → page 表 1 条（`source_url` 指向 CDN 原图）
