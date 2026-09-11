# MangaDex 源站说明（mangadex_source.py）

## 目标站
- 站名：MangaDex（mangadex.org），v5 API：`https://api.mangadex.org`
- 性质：粉丝翻译(scanlation)聚合站，**内容版权属原权利人，非授权分发**
- 合规状态：AUP 明确**仅个人/非商业**、需署名 MangaDex 与汉化组、限速约 5 req/s/IP
- 本项目定位：**学习用途 · 受控样本**（config.py `enabled=False`，不参与 serve 轮询，
  仅手动 `run --source mangadex`；单部少量章节、不发布、可按 `source=mangadex` 清理）

## API 要点（v5）

| 用途 | 接口 |
|---|---|
| 漫画级列表（按最新上传章节倒序） | `GET /manga?order[latestUploadedChapter]=desc&hasAvailableChapters=true&availableTranslatedLanguage[]=zh&limit=25&offset=0`（不带分级；列表「翻页至窗口边界」，见下） |
| 漫画详情 | `GET /manga/{id}?includes[]=cover_art&includes[]=author&includes[]=artist` |
| 章节 feed | `GET /manga/{id}/feed?translatedLanguage[]=zh&order[volume]=asc&order[chapter]=asc&includeExternalUrl=0&limit=500`（⚠️ 布尔参数须用 `0/1`，`false` 会 400） |
| 最新章时间 | `GET /chapter?manga={id}&order[publishAt]=desc&limit=1` → 取 `publishAt` |
| 章节图分发 | `GET /at-home/server/{chapter_id}` → 顶层 `{baseUrl, chapter:{hash,data[]}}`（**无外层 `data`**，见下 §⚠️） |
| 封面 | `https://uploads.mangadex.org/covers/{manga_id}/{fileName}`（顺带 cover_art 关系给出） |

## 各 API 参数说明

### ① GET /manga —— 漫画级列表
| 参数 | 本实现取值 | 可选值 / 说明 |
|---|---|---|
| `order[latestUploadedChapter]` | `desc` | 按最新上传章节倒序（「最近更新」语义）；也可 `order[followedCount]/rating/year/createdAt` 换排序 |
| `hasAvailableChapters` | `true` | 只留有可读章节的漫画 |
| `availableTranslatedLanguage[]` | `zh` | 译本语言过滤（多值：zh/en/ja…）；本实现经 feed 层再回退 en |
| `originalLanguage[]` | — | 原作语言过滤（未用） |
| `includes[]` | `cover_art` | 顺带返回的关系（cover_art/author/artist/tag） |
| `contentRating[]` | **已去掉** | safe/suggestive/erotica/pornographic 分级过滤（2026-09-08 移除） |
| `status` / `year` / `title` | — | 连载状态 / 年份 / 标题模糊搜索（未用） |
| `includedTags[]`/`excludedTags[]` | — | 按 tag UUID 过滤（未用） |
| `publicationDemographic[]` | — | shounen/shoujo/seinen/josei 读者群（未用） |
| `limit` / `offset` | 25 / 翻页 | limit ≤100；本实现增量翻至窗口边界停、全量翻到 10 页安全阀 |
| ⚠️ 不存在 | — | **无 `latestUploadedChapterSince` 这类时间过滤** → 窗口必须靠逐部查最新章时间实现 |

### ② GET /chapter —— 章节级查询（本实现：查最新章时间）
| 参数 | 本实现取值 | 可选值 / 说明 |
|---|---|---|
| `manga` | {uuid} | 按漫画 UUID 过滤章节 |
| `order[publishAt]` | `desc` | 按公开时间倒序取最新 1 条 |
| `limit` | 1 | 只取最新一章 |
| `translatedLanguage[]` / `contentRating[]` | — | 可选过滤（不带 = 全语言/全分级） |
| ⚠️ 不支持 | — | `includeFuturePublishAt`、`includeExternalUrl` 在该端点会 **400**（曾踩坑） |

### ③ GET /manga/{id} —— 单部详情
| 参数 | 说明 |
|---|---|
| `includes[]` | cover_art/author/artist（本实现用）——注意 **tag 不在此**（在 `attributes.tags`，`includes[]=tag` 无效） |

### ④ GET /manga/{id}/feed —— 章节 feed
| 参数 | 本实现取值 | 说明 |
|---|---|---|
| `translatedLanguage[]` | `zh`（空→重试 en） | 译本语言；本实现 zh→en 回退 |
| `contentRating[]` | 全部 4 值 | ⚠️ **必填**，缺省 400。取值：`safe`/`suggestive`/`erotica`/`pornographic`（**返回范围 = 声明范围**）；改分级只改代码常量 `CONTENT_RATINGS` 即可 |
| `order[volume]` / `order[chapter]` | `asc` | 按卷/话升序取全表，解析后反转成「最新在前」 |
| `includeExternalUrl` / `includeFuturePublishAt` | `0` | 布尔须用 `0/1`（`false` 400） |
| `limit` | 500 | 单次最多返回条数 |

### ⑤ GET /at-home/server/{chapter_id} —— 章节图分发
| 项 | 说明 |
|---|---|
| 路径参数 | chapter UUID（必填） |
| 查询参数 | 无（`forcePort443=true` 可选，强制 443 出图，未用） |
| 返回 | 顶层 `{result, baseUrl, chapter:{hash, data[], dataSaver[]}}`（**无外层 data**）；原图取 `data`，缩略图在 `dataSaver` |
| 图片 URL | `{baseUrl}/data/{hash}/{file}`（短时效 → 过期重拉本端点换新） |

### 封面静态域（非 API）
`https://uploads.mangadex.org/covers/{manga_id}/{fileName}` —— 无请求参数，cover_art 关系的 `fileName` 直接拼。

## 模型映射
- 1 部漫画 = manga 记录 → comic 表（`source_comic_id` = manga UUID）
- 章节 = feed 里的 chapter → chapter 表；`chapter_no` 用「卷号*1000 + 话号*10」映射
  为单调整数避免跨卷撞号（无编号/外传 → `10000+idx` 高位兜底）
- 每页图 = at-home 分发 URL → page 表（`{baseUrl}/data/{hash}/{file}`）

## 关键机制
- **时间窗口（方案 B，精确到章）**：列表按 `latestUploadedChapter` 倒序返回，但该字段是
  chapter **UUID 而非时间**（`updatedAt` 是元数据修改时间、不可作窗口基准，曾误用显示
  出 2025-11 旧日期假象）——故列表对每部漫画**逐部查 `/chapter?order[publishAt]=desc&limit=1`
  取最新章真实 `publishAt`** 作 `source_updated_at` 供 since 过滤（受控低频，25 部约 2-3 分钟）。
- **翻页至窗口边界（2026-09-08）**：增量模式不固定页数——列表按最新章时间倒序，调度器
  持续翻页；当某一页**没有任何窗口内作品**（`items` 空，即全部最新章早于 since）即视为已
  越过边界，`has_next=False` 停止（避免当天更新 >1 页时漏采）。无 since（full/首采）翻到
  `MAX_LIST_PAGES=10` 安全阀为止。
- **图床时效**：at-home 分发的 URL 短期有效，与 zaimanhua 图床同构 ——
  懒转存过期时经 `fetch_source_page_urls` 重新分发兜底。
- **语言**：**优先中文 · 英文兜底**（详见下「语言策略」小节）——分两层口径：
  列表层只收中文译本；同一部漫画内的章节/标题/描述走 `zh → en` 降级。
- **受控参数**：`LIST_LIMIT=25`、`MAX_LIST_PAGES=10`（安全阀）、`FEED_LIMIT=500`、`MIN_DELAY=0.6s`；
  列表不带分级；feed 端点带 `contentRating[]` 全部 4 值（`CONTENT_RATINGS` 常量，**必填否则 400**）；排除 externalUrl 外链章节。
- 列表项顺带从 cover_art 关系解析封面（免详情页二次请求）。
- **可读性探测（`_readable_head`）**：detail 时向前探测若干章 at-home 图数，把「真正有图
  可读」的最新章放到 chapters 首位——规避个别无图/站外托管章被当成最新话导致首采 0 页。

## 语言策略（优先中文 · 英文兜底，2026-09-08 明确）

MangaDex 里「同一话中英双语」与「多语言字段」是两层概念，处理方式不同，因此分为
**列表层**与**字段层**两个口径：

| 层次 | 策略 | 实现位置 |
|---|---|---|
| 漫画列表（最近更新） | **只收中文译本**：`availableTranslatedLanguage[]=["zh"]`，无中文译本的英文漫画**不进入**该源 | `fetch_comic_list` |
| 章节 feed | **中文优先 · 英文兜底**：`translatedLanguage[]` 先 zh、空则 en | `_fetch_feed` |
| 标题 | **中文优先 · 英文兜底**：主 `title` zh→en→任意；再扫 `altTitles` 的 zh → (en/zh-hk/zh-cn) → 最终 main | `_comic_title` |
| 描述 | **中文优先 · 英文兜底**：`description.zh` → `description.en` → 空（再回退为标题） | `_description` |

### 章节级多版本（同一话有 zh / en 两条独立记录）
MD 的"同一话中英双语"本质是**两条独立 chapter 记录**（不同 id、同卷同话、不同语言）。
适配器**不合并，整部只取一个语言**：

```python
for lang in ("zh", "en"):          # zh 优先，en 兜底
    params["translatedLanguage[]"] = [lang]
    raw = self._api_get(f"/manga/{manga_id}/feed", params)
    rows = raw.get("data") or []
    if rows:
        chapters = self._parse_feed(rows)
        break                       # 拿到 zh 立即 break，不再请求 en
```

结果：同一部漫画内，有中文则**只留中文**（英文版在请求层被过滤，不会作为另一章
重复入库，`_chapter_key` 卷×1000+话×10 保持唯一）；无中文才整体回退英文。
列表层同理用 `availableTranslatedLanguage[]=["zh"]`，只列有中译本的漫画。

### 字段级多语言（title / description 是单个"多 key 对象"）
标题、描述**不是**分语言的独立记录，而是同一对象的多个 key
（`{"zh":..., "en":..., "ja-ro":...}`），取值做**语言降级**：

```python
def _comic_title(attrs):
    main = _title(attrs.get("title"))        # zh → en → 任意，取首个非空
    for alt in attrs.get("altTitles") or []: # 先扫 altTitles 找中文名
        if (val := alt.get("zh")): return val.strip()
    for alt in attrs.get("altTitles") or []: # 其次英文/繁/简
        if (val := alt.get("en") or alt.get("zh-hk") or alt.get("zh-cn")): return val.strip()
    return main

def _description(d):
    return (d.get("zh") or d.get("en") or "").strip()
```

> ⚠️ 细节：MD 中文译本作品常把**罗马字/日文音译**放主 `title`、**中文名放 `altTitles`**，
> 所以 `_comic_title` **先扫 `altTitles` 的 zh**，找不到才用主 title——保证中文译本展示
> 中文名而非 `ja-ro` 音译名。

### 不涉及语言的字段
| 字段 | 取值方式 | 语言相关 |
|---|---|---|
| 作者 / 画师 | `relationships` 里 `type=author/artist` 的 `attributes.name` | 否（单值） |
| 标签 | `attributes.tags[].attributes.name`（`_title` 取 zh→en→任意） | 是（zh 优先） |
| 状态 | `status` 枚举映射：ongoing→连载 等 | 否 |

## 合规红线
- 本 demo 允许的"站点学习"仅指本地技术演示的受控样本；公开发布需另行授权与合规评估。

## 实测验证记录（2026-09-08 端到端跑通）

在受控样本范围内完成了一次完整的今日增量采集 + 懒转存闭环（种子水位播种到
昨日 23:59:59，只收"今天更新"的漫画）：

- **增量采集**：`cli run --source mangadex`（读 sync_log 水位）→ **7 部今日漫画**，
  登记章节页 URL（含 at-home 分发地址）共 **196 页**，封面经 `ensure_cover_local`
  幂等落盘；
- **懒转存（2 路并发）**：`cli transfer-images` → `checked:179, transferred:179, failed:0`
  （179 为本次未转存页数，其余此前已转存），页面状态分布 `已转存:277`（含
  zaimanhua/mangadex 等当时的各源全部页；demo_source 已于 2026-09-11 移除，此处为当时的记录）；
- **性能**：2 路并发下 MangaDex 单张 3~5s，179 页全程 **5 分 32 秒** 跑完；
  串行基线约 45 分钟（瓶颈为境外图床带宽，见 crawler-service/README.md「并发转存」）；
- **API 真图验证**：`GET /api/images/{mangadex_comic_id}/{chapter_id}/{page_no}` →
  HTTP 200、`Content-Type: image/jpeg`、`Content-Length: 2,316,275`，文件头
  `\xff\xd8\xff\xe1`（JPEG SOI），确认非 SVG 占位 —— 前端 5173 可正常展示 MangaDex 真图。
- 库内总量（当日）：`comic=16, chapter=18, page=277`。

> 验证用的漫画样本《独狼女孩的单相思》(comic=10, chapter=12) 分页图
> `/api/images/10/12/{1,5,12}` 均已返回 2.08~2.32MB 真实 JPEG。

## ⚠️ at-home 响应结构（2026-09-08 实测修正）
- MD 的 at-home 响应**没有外层 `data`**：顶层直接是 `{result, baseUrl, chapter:{hash, data[]}}`。
  曾误按 `data.chapter` 解析导致图片恒为空、误判"MD 无图"（实际图完全可下载，见下）。
- 图片 URL = `{baseUrl}/data/{hash}/{文件名}`（dataSaver 缩略图在 `dataSaver` 数组）。
- 下载无需 Referer（带 Referer: mangadex.org 更稳）；单章实测 27 张、第 1 张 1.09MB PNG 200 OK。
- 少数官方/授权章的 `data` 确实为空（图在站外官方源），`_readable_head` 会探测可读性把
  有图章提前——但 MD 站内图整体可用，非生态性缺失。
