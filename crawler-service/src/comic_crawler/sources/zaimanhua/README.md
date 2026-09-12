# zauimanhua / 再漫画 适配器接口说明

> 目标站：`https://zaimanhua.com`（PC） / `https://m.zaimanhua.com`（H5 · 品牌「再漫画」）
> 适配器源码：`crawler-service/src/comic_crawler/adapter/zaimanhua_source.py`
> 接口逆向时间：2026-09-02 实测确认；本文件为**持久化参考**，避免每次重新探测。

## 1. 两条通道（关键结论）

同一内容库、同一 id 体系，但**按 `Platform` 请求头区分下发内容**：

| 通道 | 域名 | 鉴权 | 章节下发 | 图床 |
|---|---|---|---|---|
| PC 站 | `www.zaimanhua.com` / `manhua.zaimanhua.com` | 需 Bearer token（`token.js` 写死 `pc`） | **部分书返回空章节**（`canRead=False, chapterList=[]`）— 与是否登录无关 | `images.zaimanhua.com` |
| H5 站 | `m.zaimanhua.com` | **匿名即可读** | 正常下发 | `images.zaimanhua.com`（同域） |

> ⚠️ 不要被「手机登录才能看到」误导：差异在 `Platform` 头，与登录态无关。
> **本适配器一律走 H5 通道**（`m.zaimanhua.com`）。

## 2. 请求公共头（所有接口通用）

```
User-Agent: iPhone UA（见 UA_H5）
Platform: h5                 # 关键！决定服务端是否下发章节
Origin: https://m.zaimanhua.com
Referer: https://m.zaimanhua.com/pages/comic/page
content-type: application/json
```

统一查询参数：`_v=15`（uni-app 默认版本号，必需）。

实现于 `_api_get()`：内置 3 次重试 + 指数退避（0.8s/1.6s/2.4s），超时 12s，跟随重定向。

## 3. 接口清单

### 3.1 最近更新列表（首页「最近更新」标签）

```
GET /api/app/v1/comic/update/list/0/{page}
```

- `page`：分页，从 1 递增；**每页 20 部**
- 返回 `data` 是 **list**（非 dict），每行字段：
  - `comic_id`（作品ID，**注意 `id` 恒为 0，必须用 `comic_id`**）
  - `title` / `authors` / `cover` / `types` / `status` / `islong` / `comic_py` / `alias_name`
  - `last_update_chapter_name`（最新章节名）/ `last_update_chapter_id`（最新章节ID）
  - `last_updatetime` / `last_update_volumn`
- **`last_updatetime`（Unix 秒级时间戳）是增量窗口过滤的字段** → 适配器解析成
  `ComicBrief.source_updated_at`（见 §3.1.1）
- 无明确 `has_next` 标志：以「本页满 20 部 && page < MAX_PAGE」判断
- 受控参数：`MAX_PAGE = 1`（只扫首页，避免一次收录过多）

### 3.1.1 时间窗口增量（`since` 过滤）

图源列表接口自带 `last_updatetime` 秒级时间戳，故再漫画**支持精确到秒的窗口过滤**：

```python
def fetch_comic_list(page=1, since=None):
    items = [self._row_to_brief(row) for row in list_data[:20] ...]
    # 增量窗口：只保留源站更新时间 > since 的漫画（首次 since=None 全收）
    if since is not None:
        items = [it for it in items
                 if it.source_updated_at is not None and it.source_updated_at > since]
    return ComicListResult(items=items, page=page, has_next=has_next)
```

- `since` = 上次同步完成时间（`sync_log.finished_at`，调度器通过
  `Storage.get_last_sync_time(source)` 读取后传入），`None` = 首次/全量
- **精确到秒**：`source_updated_at > since`（注意是严格大于，保证边界不含已同步的）
- 实测：`since=2026-09-05 11:35:30` 后只剩 1 部《今朝摇曳依旧》，其余 19 部被正确过滤
- 受控限制：`MAX_PAGE=1` 只扫首页最近更新 20 部（接口仅暴露最近更新榜，无当日翻页能力）

### 3.2 详情（漫画信息 + 章节卷组）

```
GET /api/app/v1/comic/detail/{cid}
```

- 返回 `data.data` 为漫画信息，含 `chapters` **卷组数组**：
  ```
  chapters: [
    { title: '连载',   data: [ {chapter_id, chapter_name, chapter_order, ...}, ... ] },
    { title: '单行本', data: [ ... ] },
    { title: '番外篇', data: [ ... ] }   # 部分作品有
  ]
  ```
- 卷组内 `data` 为**倒序（新 → 旧）**，即 `data[0]` 是最新一话
- 每章关键字段：`chapter_id`（源站章节ID）、`chapter_name` / `chapter_title`（标题）、`chapter_order`（**全局有序整数，最可靠的排序/唯一键**）

**实测章节量（2026-09-03）**：

| 漫画 | cid | 连载卷 | 单行本 | 番外 |
|---|---|---|---|---|
| 午夜心旋律 | 71419 | 130 章 | 9 卷 | — |
| 学园奶爸 | 7828 | 149 章 | 13 卷 | 12 卷 |

> 每部漫画的 `chapter_order` 均**唯一**（唯一数 = 章数），可作为 `(comic_id, chapter_no)` 唯一键。

### 3.3 章节图列表

```
GET /api/app/v1/comic/chapter/{comic_id}/{chapter_id}
```

- 返回 `data.data.page_url`：该章节所有正文页的**签名 CDN 地址数组**
- URL 自带 `sign`/`t` 防盗链签名，**无 Referer 限制可直接下载**
- ⚠️ 签名**短时效**（实测约数日过期）：采集入库的 page_url 只是快照，批量晚转存会 403。
  懒转存已内置兜底（2026-09-07）：`lazy_transfer` 本地解析 URL `t` 预判过期，过期或下载
  失败时经适配器 `fetch_source_page_urls` 现场重新请求本接口重签 URL 再下载；无需手动重采。

### 3.4 搜索（**按需导入用**，2026-09-12 启用）

```
GET /api/app/v1/search/index?keyword=..&source=0&page=1&size=20
```

- 返回 `data.list`（与 3.1 同构），**`id` 即作品 ID**（而 3.1 的作品 ID 在 `comic_id`、
  其 `id` 恒为 0）—— 适配器用 `_row_to_brief(row, id_field="id")` 区分这两处语义。
- 用途：搜索页「其他来源」+ 按需导入（`search_comics` / `parse_comic_ref`）。

### 3.5 可读性判定与图片域名白名单（2026-09-12）

- **⚠️ 详情接口的逐章 `canRead` 不可靠，别拿它判不可读**：实测「午夜心旋律」(71419)
  详情里 131 章 `canRead` **全为 false**，但章节接口对**最新的 130 话**返回
  `canRead=true / page_url 21 条` —— 该字段是未计算的默认值。
  **可靠判据是章节接口本身**：探一章看 `page_url` 是否非空
  （`scheduling/ondemand._probe_readable`：先探最新章、再退最老章，最多 2 次请求，任一可读即放行）。
  适配器的 `restricted` 只认明确的 `is_lock`。
- **源站可能部分章节没有数据**：71419 的 **1、2 话** `page_url` 就是空的
  （已核对：是**源站没有这两话的数据**，与收费/限免无关），而 130 话有 21 页。
  接口层面**无法区分「数据缺失」与「需付费」**，因此不做归因，只按「能否取到图」处理：
  只要**任一章**能取到图就允许导入，取不到的章节届时回落占位图。
- **`image_hosts = {"images.zaimanhua.com"}`**：正文图与封面都在该图床域（带 `sign+t`
  短时效签名）。声明后，转存与读时穿透取图只允许下载该域，防止库内 URL 被当作任意请求跳板。

## 4. 章节号（chapter_no）取 key

- **主取**：源站 `chapter_order`（全局有序整数，精确区分分卷小话，如 `153.5话=1680` / `153话=1670`）
- **回退**：仅在 `chapter_order` 缺失/非法时用 `_chapter_no()` 正则解析（只认整话 `第128话`→128；含小数点 `第153.5话` **拒绝解析返回 None**，避免误读成 `5`)
- 采集范围：`VOL_TITLE = "连载"`，只收连载卷全部话，跳过单行本 / 番外卷（避免章节编号语义混杂）

## 5. 受控参数（学习用途 · 受控样本）

```python
MAX_PAGE = 1        # 「最近更新」最多扫描页数（每页 20 部）
VOL_TITLE = "连载"  # 只收连载卷全部话，跳过单行本卷
```

> 说明：早期版本有 `MAX_CHAPTERS = 2`（每部只收连载卷最新 2 话），
> 2026-09-03 已改为「取连载卷**全部**话」，故 `MAX_CHAPTERS` 已删除。

## 6. 模型映射

- 1 部漫画（`comic_id`）→ comic 表 1 条
- 连载卷每个 chapter 入口 → chapter 表 1 条（`chapter_no = chapter_order`）
- 每张正文图（page_url）→ page 表 1 条（存签名 CDN 原图 URL）

### 6.1 标签（题材）关联表设计（2026-09-04 规范化）

原来 `comic_tag(comic_id, tag)` 直接存标签字符串（有重复）。现改为**规范化 3 表**：

- `comic.category`：**不改动**，保留源站 `types` 拼出的完整串（如 `爱情, 美食`）
- `tag(id, name)`：**标签字典表**，每个唯一标签一行（name 唯一，去重）
- `comic_tag(comic_id, tag_id)`：**关联表**，只存引用，不再冗余存 tag 字符串

查询（分类 / 搜索 / 标签列表）统一通过 `comic_tag JOIN tag` 取 `tag.name`。
`types` 字段（`[{'tag_name':'爱情'},...]`）在适配器里拆分为 `tags` 列表，入库时经
`_sync_tags` upsert 进 `tag` 字典表 + 写 `comic_tag` 关联表（先清后插，幂等）。
