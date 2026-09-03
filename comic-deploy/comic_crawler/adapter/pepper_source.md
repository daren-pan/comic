# pepper Pepper & Carrot 适配器接口说明

> 目标站：`https://www.peppercarrot.com`
> 适配器源码：`crawler-service/src/comic_crawler/adapter/pepper_source.py`
> 授权：**CC-BY 4.0**（官网 `/en/license/`，允许抓取/分享/改编，需署名作者 David Revoy）
> 本文件为**持久化参考**，记录接口与解析要点。

## 1. 站点概况

- **没有独立 JSON API**，纯 HTML 服务端渲染
- 全站抓取 `parsel.Selector` + XPath
- 一部 webcomic、一个 episode = 一话（章节），全站就一部《Pepper & Carrot》
- `robots.txt` 仅 Disallow `/cache/` 与 `/extras/temp/`
  - 本适配器抓取 `/en/webcomics/`（列表）与 `/0_sources/`（正文图）均在允许范围
  - **刻意避开 `/cache/` 缩略图**
- 正文图使用官方公开 **low-res** 版本（尊重版权方带宽，足够演示）

## 2. 请求方式

- 走通用 `HttpFetcher`（桌面 UA 池，返回 HTML 文本）
- 用 `http.get(url)` + `Selector(text=html)`
- **需注意**：`HttpFetcher` 不支持自定义头；本源无需自定义头

## 3. 接口/页面清单

### 3.1 列表页（站点即一部漫画）

```
GET /en/webcomics/peppercarrot.html
```

- 站点固定只有 1 部漫画（`Pepper & Carrot`，作者 David Revoy）
- 返回单个 `ComicBrief`，`source_comic_id = "pepper-and-carrot"`
- 最新章节名：`(//figure[contains(@class,'thumbnail')])[1]//figcaption//a` 文本
- **封面空**：列表页缩略图在 `/cache/`（robots 禁抓），封面由详情阶段从正文页补

### 3.2 详情页（解析列表页全部 episode → 章节）

```
GET /en/webcomics/peppercarrot.html   （即 comic.detail_url）
```

- 章节节点：`//figure[contains(@class,'thumbnail')]`
- 每节点取：
  - 标题：`.//figcaption//a` 文本
  - 链接：`.//figcaption//a/@href` → 匹配 `EPISODE_PATH_RE = /en/webcomic/ep(\d+)_([^/]+)\.html`
  - 章节号：`episode 编号`（`ep(\d+)` 的 `\d+`），`chapter_no = ep_no`
  - `source_chapter_id = "ep{ep_no}"`
- 受控参数：`MAX_EPISODES = 10`（只取最新 N 话）
- **封面补取**：从最新一话的正文页取 `//img[contains(@alt,'Header')]/@src`（`/0_sources/`，robots 允许）

### 3.3 章节页（正文图）

```
GET /en/webcomic/ep{no}_{slug}.html   （即 chapter.pages_url）
```

- 正文图：`//img[starts-with(@title, 'Page')]/@src`
- 按 `@title` 以 `Page` 开头的 img 即为漫画内页，顺序即页序
- 返回 `page_no` 从 1 递增

## 4. 章节号（chapter_no）取 key

- 直接用 episode 编号（`chapter_no = ep_no`），天然唯一、严格递增
- 无需正则解析标题

## 5. 受控参数（学习用途 · 受控样本）

```python
MAX_EPISODES = 10   # 只取最新 N 话（改大即全量收录）
```

## 6. 模型映射

- 1 部漫画 = Pepper & Carrot → comic 表 1 条
- 每个 episode = 一个章节 → chapter 表 1 条（`chapter_no = ep_no`）
- 每张正文图 = 一页 → page 表 1 条（`source_url` 指向 low-res 原图）
