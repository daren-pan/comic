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

### 3.1 列表页（首页「最近更新」）

```
GET /
```

- 目标区块：`//section[contains(@class,'latest-section')]//article[contains(@class,'update-card')]`
- 每张卡片取：
  - 作品ID：`comic.php?id=(\d+)`（从 `<h3><a>` 的 href 提取）
  - 标题：`.//h3/a` 文本
  - 封面：`.//img[contains(@class,'cover')]/@src`
  - 分类：`.//*[contains(@class,'update-tags')]` 文本
  - 最新章节名：`.//*[contains(@class,'update-chapter')]` 文本
- 受控参数：`MAX_COMICS = 4`（取首页前 N 部）

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
MAX_COMICS = 4      # 首页「最近更新」取前 N 部
MAX_CHAPTERS = 3    # 每部仅收录主线最新 N 话
BANNED_TEXTS = ("开始阅读", "去阅读", "最新更新")   # 章节列表功能链接
```

## 6. 模型映射

- 1 部漫画（comic_id）→ comic 表 1 条
- 每个章节入口 → chapter 表 1 条（`chapter_no` 见 §4）
- 每张正文图 → page 表 1 条（`source_url` 指向 CDN 原图）
