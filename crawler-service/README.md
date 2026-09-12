# comic-crawler 采集服务（骨架实现）

漫画聚合平台（架构方案见 `../docs/architecture.md`）的采集层落地代码。
演示完整链路：**调度 → 抓取 → 解析 → 指纹去重 → 入库 → 图片懒转存 → 失效巡检 → 同步日志**。

## 目录结构

分层约定：**通用在外、扩展在里；依赖只能由内向外**（`scheduling` → `sources`/`storage`/`images` → 契约 → 通用件），由 `tests/test_layering.py` 断言守卫。

```
crawler-service/
├── src/comic_crawler/
│   ├── models.py              # L0 通用内核 · 领域模型 Comic/Chapter/Page/ListResult/SyncStats
│   ├── config.py              # L0 通用内核 · 源站配置数据结构 SourceConfig，不含各源清单
│   ├── http.py                # L0 通用内核 · 抓取客户端：UA 池 / 随机延迟 / 指数退避 / 代理池预留
│   ├── fingerprint.py         # L0 通用内核 · 标题归一化 + 跨站指纹（跨源去重核心）
│   ├── paths.py               # L0 通用内核 · 路径常量（服务根 / 图库根唯一真源）
│   ├── cli.py                 # 命令行入口（run / transfer-images / inspect / list / show / serve）
│   ├── sources/               # 源站层：契约在外，各源在里
│   │   ├── base.py            #    L1 契约 · CrawlerAdapter 抽象接口（新增源站的唯一接入点）
│   │   ├── registry.py        #    L1 契约 · 适配器注册表（@register 装饰器）
│   │   ├── __init__.py        #    聚合各源子包 → SOURCES（管理台展示顺序）
│   │   └── <源名>/            #    L2 实现 · 每个源一个自包含子包
│   │       ├── __init__.py    #      导出适配器类 + 该源 SOURCES 配置（频率/启停就近维护）
│   │       ├── adapter.py     #      CrawlerAdapter 实现（列表 / 详情 / 章节图解析）
│   │       ├── README.md      #      接口路径 · 请求头 · 分页 · 限流 · 已知坑
│   │       └── fixtures/      #      该源样例 HTML（离线测试）
│   ├── storage/               # 存储层：契约在外，实现在里
│   │   ├── base.py            #    L1 契约 · Storage + UserStore 抽象（上层只认它）
│   │   └── mysql/             #    L2 实现 · MySQL（本项目唯一后端）
│   │       ├── _util.py       #      连接 / 热度算法 HEAT_* / 时间归一
│   │       ├── comic_store.py #      MySQLStorage：漫画/章节/页/同步日志 + 只读查询
│   │       └── user_store.py  #      MySQLUserStore：用户/收藏/阅读历史
│   ├── images/                # 图片层：契约 + 本地实现 + 懒转存
│   │   ├── store.py           #    ImageStore 抽象 + 本地模拟 OSS + default_store_root() 图库根
│   │   └── transfer.py        #    懒转存 + 读时穿透取图（本地没有就现场取回并顺手落盘）+ 封面落盘
│   └── scheduling/            # 编排层：何时跑 / 跑一次做什么
│       ├── sync.py            #    采集主流程：增量轮询 / 全量扫描
│       ├── ondemand.py        #    按需导入：收录用户指定的单部作品（搜索 / 链接 / ID）
│       ├── heal.py            #    失效巡检 + 封面自愈
│       └── scheduler.py       #    轮询式定时调度（增量 / 每日全量 / 每小时巡检）
├── tests/                     # 单元测试（含 test_layering.py 分层守卫）
└── requirements.txt
```

> 样例 HTML 已**就近**放进各源子包的 `fixtures/`（跟着源走），不再集中在一个顶层目录。

## 快速开始

```bash
# 1. 创建虚拟环境并安装依赖
python -m venv .venv
.venv/Scripts/pip install -r requirements.txt     # Windows
# .venv/bin/pip install -r requirements.txt       # macOS/Linux

# 2. 增量同步（**主源**：再漫画 zaimanhua —— 会联网；受控样本请加 --limit）
PYTHONPATH=src python -m comic_crawler.cli run --source zaimanhua --limit 3

# 3. 备源（各自独立采集，跨站重复作品由指纹自动合并）
PYTHONPATH=src python -m comic_crawler.cli run --source mangadex
PYTHONPATH=src python -m comic_crawler.cli run --source weebcentral

# 4. 图片懒转存（模拟用户阅读触发的按需转存）
PYTHONPATH=src python -m comic_crawler.cli transfer-images

# 5. 失效巡检（转存未转存页 + 全表校验已转存对象 + 恢复丢失）
PYTHONPATH=src python -m comic_crawler.cli inspect

# 6. 查看库内数据 / 列出已注册适配器
PYTHONPATH=src python -m comic_crawler.cli show
PYTHONPATH=src python -m comic_crawler.cli list

# 7. 跑单元测试（54 个用例，纯逻辑：不连数据库、不写临时文件）
PYTHONPATH=src python -m unittest discover -s tests -v

# 8. 定时调度守护（增量轮询 / 每日全量 / 失效巡检，Ctrl+C 退出）
#    - 增量间隔取各源 `sources/<源名>/__init__.py` 里的 crawl_interval_seconds
#    - 每日凌晨 3 点后每源跑一次全量；失效巡检每小时一次（全表键集分页校验）
#    - --source 可只调度指定源；--interval 调整轮询检查粒度（默认 30s）
PYTHONPATH=src python -m comic_crawler.cli serve
```

## 存储：MySQL（项目唯一方案）

采集服务与 API 服务统一使用 MySQL 作为唯一存储实现（`MySQLStorage`），
`Storage` 抽象作为类型契约保留（架构方案 §3.1「抽象可替换」的落地）。

```bash
# 0. 前置：本机 MySQL 可用（默认连 127.0.0.1:3307，兼容 RuoYi-Cloud 的 docker mysql）
#    连接参数可用环境变量覆盖：
#    COMIC_MYSQL_HOST / COMIC_MYSQL_PORT / COMIC_MYSQL_USER / COMIC_MYSQL_PASSWORD / COMIC_MYSQL_DB

# 1. 建库建表（comic 库 + 9 张表，utf8mb4）
mysql -h127.0.0.1 -P3307 -uroot -p -e "CREATE DATABASE comic DEFAULT CHARACTER SET utf8mb4;"
mysql -h127.0.0.1 -P3307 -uroot -p comic < sql/mysql_schema.sql

# 2. 采集链路直接写 MySQL（无需迁移）
PYTHONPATH=src python -m comic_crawler.cli run --source zaimanhua --limit 3
PYTHONPATH=src python -m comic_crawler.cli transfer-images
PYTHONPATH=src python -m comic_crawler.cli inspect

# 3. API 服务同库（前端零改动）
uvicorn main:app --port 8000   # 在 api-service 目录
```

**表结构约定**（DDL 见 `sql/mysql_schema.sql`）：

- **时间列一律用 `DATETIME`**：`chapter/comic.sync_time`、`comic.addtime`、`sync_log.started_at`/`finished_at`、`favorite.created_at`、`history.read_at`、`user.created_at`。**不要用 `VARCHAR` 存 ISO 串**——字符串比较/排序/时区语义都是坑（2026-09-10 已由 `varchar(32)` 统一迁移为 `DATETIME`，写入侧 `_now()` 直接给 `datetime`）；
- 标签走 `tag` + `comic_tag` 关联表（`comic.category` 保留源站原始串）；
- 封面 / 分页图只存**图库内相对 key**（`covers/26.jpg`、`comic/26/34/001.jpg`）；
- **热度不落库**：只存真实计数 `comic.views`（浏览次数），热度由 `heat_sql()` 实时算
  （`1000 + 浏览×1 + 收藏×2`），同分再按 `sync_time` 倒序。权重是 `HEAT_BASE` /
  `HEAT_PER_VIEW` / `HEAT_PER_FAVORITE` 三个常量 —— 改算法只改这里，无需回填。⚠️ 统计收藏数用
  `COUNT(DISTINCT f.user_id)`（`favorite` 一行 = 一对用户/漫画，**不能用 `f.id`**——那会让多行变一行）。
- **每张表都有自增代理主键 `id`**（含关联表 `comic_tag`/`favorite`/`history`）：`id` 是与业务无关的
  稳定行标识，为后续扩展留余地（引用单行、加字段、做流水/审计、分库分表）。**业务唯一性用
  `UNIQUE KEY` 单独表达** —— `comic_tag` 有 `uk_comic_tag(comic_id, tag_id)`、`favorite`/`history`
  有 `uk_user_comic(user_id, comic_id)`。幂等写入依赖的就是这些唯一键（`INSERT IGNORE` / `ON DUPLICATE
  KEY UPDATE`），**不是主键**，所以主键换成 `id` 不影响原有语义。⚠️ `favorite` 无 `comic_id` 单列索引时
  由 FK 自动补（`fk_fav_comic`）；统计收藏数用 `COUNT(DISTINCT f.user_id)`。

## 接入一个新源站

全程**只动 `sources/` 一个子包**，业务/存储/调度层零改动：

1. **复制模板**：`cp -r sources/zaimanhua sources/<新源名>`（zaimanhua 是结构最完整的真实源）；
2. **写适配器**：改 `adapter.py` —— `source_name`、`@register(...)`、`base_url`，
   再按目标站真实 DOM 改写三个方法；四个文件各司其职：

   - `fetch_comic_list(page, since)` —— 列表页 → 漫画摘要 + `has_next`；
   - `fetch_comic_detail(comic)` —— 详情页 → 简介 + 章节列表；
   - `fetch_chapter_pages(detail, chapter)` —— 章节页 → 分页图片。

3. **声明配置**：改该子包 `__init__.py` 的 `SOURCES = [SourceConfig(name="<新源名>", ...)]`
   （频率/启停**就近维护在这里**，不再集中到 `config.py`）；
4. **登记**：在 `sources/__init__.py` 的 `_SOURCE_PACKAGES` 加一项；
5. **可选能力**（按目标站实际支持情况声明，上层据此决定给不给入口）：

   - `capabilities = {"search", "ref"}` —— 支持关键词搜索（覆写 `search_comics`）
     与作品链接/ID 解析（覆写 `parse_comic_ref`）。两者齐备后，搜索页才会出现
     「其他来源」与「导入并阅读」；
   - `image_hosts = {"图床域名"}` —— 允许下载的图片域名白名单（转存与穿透取图都校验，
     防 SSRF）。图床与站点不同域的源务必补上。

子包固定 4 件套：`__init__.py`（导出 + SOURCES）、`adapter.py`（解析）、
`README.md`（接口/请求头/限流/已知坑）、`fixtures/`（离线样例，可选）。

跨站重复作品由 `fingerprint.py` 自动合并（标题归一化 + 作者 → sha1 前 16 位，
命中同一指纹只保留一条记录）。

## 按需导入（用户指定看哪一部）

采集只能碰到源站「最近更新」榜上的作品；**按需导入**正好相反 —— 用户给出**
一部作品（关键词 / 作品链接 / 作品 ID），把它收进库。入口是搜索页的
「其他来源 → 导入并阅读」，或直接 `POST /api/admin/import`。

| 环节 | 行为 | 请求数 |
|---|---|---|
| 详情 | 拿书目 + **全部章节** | 1 |
| 书目 | 写 `comic` 1 行（幂等：指纹 + `(源, 源作品 ID)` 双唯一键） | — |
| 章节 | **全量收目录**（`first_chapters=None`，且补齐库内缺的那几话） | — |
| 页清单 | **一页都不登记**（`register_pages=False`） | 0 |
| 图片 | **一张都不下载**（封面除外，落 `covers/{id}.jpg`） | 1 |

所以导入 100 话也只花 1~2 次请求、约 2 秒。页清单与图片都在用户**真正打开那一话**
时才产生：`/api/chapters/{id}/pages` 现场登记页清单（`api-service/services/ondemand.py`），
`/api/images/...` 本地没有就**穿透源站取回这一张、顺手落盘**
（`images/transfer.fetch_page_bytes`）—— 用户等待只等于「源站响应一张图」，
而不是「整话下载完」。

**不保存也不展示章节页数**：源站只有「单话章节接口」能给出页数（`picnum`），**没有任何批量途径**
（列表 / 详情 / 搜索接口都不带页数，实测确认），逐话拉取既慢、又会被源站软限流（密集请求返回空）。
因此 `GET /api/comics/{id}/chapters` 只返回章节元数据，**不含页数**；
`get_chapters` / `get_chapter` 也不再做 `COUNT(page)` 统计（少一次 JOIN，接口更快）。
页清单本身仍然按需产生：用户打开某一话时才登记（`ensure_chapter_pages`），图片由穿透过取回。

**不可读内容会被拒绝，但判据必须可靠**：详情接口的逐章 `canRead` **不可信**
（实测「午夜心旋律」详情里 131 章全为 false，实际最新话可读 21 页 —— 那是未计算的默认值），
所以 `import_comic` 改为**实测探测**（`_probe_readable`：先探最新章、再退最老章，
最多 2 次请求），任一章取到图就放行 —— 源站**部分章节没有数据是常见情况**
（如 71419 的 1、2 话；接口分不清是数据缺失还是需付费，故不归因）。
只有 `is_lock` 为真、或探测全空，才抛 `ComicRestricted` 拒绝。

## 章节采样（首次只收最新一话 · 页面全部懒下载）

- 新漫画首次收录：只入库连载卷**最新 1 话**（`FIRST_CHAPTERS = 1`），不做全卷历史抓取；
- 已收录漫画：后续增量只补 `chapter_no` 大于库内最大章号的新章节（源站更新几话补几话，
  由增量时间窗口决定本轮覆盖哪些漫画）；
- 所有章节页面入库时**仅登记源站 URL**（`cached_status = '未转存'`），采集过程不主动下载
  任何图片字节 —— 真正的图片下载全部由「懒转存」按需触发（见下节）。

## 图片链路（懒转存 + 失效巡检）

- 同步入库时图片只记 `source_url`，`cached_status='未转存'`（不预抓全量图片）；
- `transfer-images` / 阅读服务触发 `lazy_transfer`：下载 → 写入 ImageStore →
  回填 `oss_url`、状态置 `已转存`；
- **下载器连接复用**：`images.transfer.default_downloader` 用模块级 `httpx.Client` 单例
  （keep-alive），批量转存不重复做 TCP/TLS 握手。**实测结论（2026-09-08）**：
  复用连接对**国内图床**显著有效（zaimanhua 单张 365KB 约 0.32s）；但**境外图床**
  （如 MangaDex `*.mangadex.network`）带宽才是瓶颈——单张 2.26MB 大图即使复用连接
  仍需 9~25s（瓶颈非握手，keep-alive 在此无优势），因此对境外源靠**并发**解耦；
- **并发转存**（`images.transfer.CONCURRENCY = 2`，默认 2 路）：`lazy_transfer` 用
  `ThreadPoolExecutor(max_workers=2)` + 抽出的 `_transfer_one(row)` 并发处理。
  实测 MangaDex 从原串行 179 页约 45 分钟缩短到 **5 分钟**跑完（单张 3~5s）。
  并发安全：`MySQLStorage` 每方法独立连接(autocommit)、`httpx` 共享 client 走线程安全
  连接池、`LocalImageStore.put` 独立文件写。低频合规：MangaDex AUP 约 5 req/s，2 路远低于该值；
- **签名过期兜底**：短时效签名源（zaimanhua 的 `images.zaimanhua.com` URL 带
  `sign+t`，数日过期；mangadex 的 at-home 分发 URL 同样短时效）——`lazy_transfer`
  先本地解析 URL 的 `t` 预判过期：过期则经适配器 `fetch_source_page_urls` 现场重拉
  该章新鲜 URL 再下载，未过期直接下载、失败再重拉兜底一次（无签名源如 weebcentral
  永久有效，恒走直接下载）；
- `transfer-images --since <ISO> [--until <ISO>] [--limit N] [--source <name>]`：只转存该时间范围内入库的
  未转存页（按章节 `sync_time`(DATETIME) 过滤，边界**双端含**：`--until` 只给日期时含当天全天）
  ——配合增量采集：先跑一次增量，再用
  `--since 增量开始时间` 调本命令，就只转本次增量新收的页；**默认把窗口内所有未
  转存页全部转掉**，`--limit` 只是可选的兜底阀门（默认不限制，需分批时才填）；
  `--source` 限定**只转存某数据源**的页
  （`lazy_transfer` 内部透传给 `list_uncached_pages` 按 `co.source` 过滤），用于
  单独补转某一个源（如管理台"仅转存某源"）；
- `inspect` 巡检：**转存未转存页 + 全表校验已转存对象是否存在 + 丢失自动恢复**。
  第 2 步（校验）按 `id` **键集分页**遍历全表（每次 `SCAN_BATCH=1000` 条，用返回行的最大
  `page_id` 推进游标直到扫完），**不会被固定条数截断**——旧实现只取 500 条且 `ORDER BY id`，
  每轮都只校验 id 最小的同一批页，其余页从未被校验/恢复。
  `inspect_sync(storage, image_store, adapter_provider, source, since, until)`：
  `source/since/until` 只作用于「转存」部分（与 `transfer-images` 同语义），`source` 同时限定校验范围；
  全部留空 = 全库巡检。
- **管理台「触发巡检」**（`POST /api/admin/inspect`）与命令行 `inspect` 走同一函数；与「触发转存」的区别是多做了上面的第 2 步校验。巡检是**全库**动作，故管理台只在页面顶部放**一块**面板，不随源卡片复制。
  命令行可选参数：`--source <name>`（只巡检某源）、`--since/--until`（只限定「转存」部分的时间窗，校验始终覆盖全表）。
- **封面自愈**（`scheduling.heal.heal_covers`）：修复图库中缺失/未落盘的封面——封面仍是外链 → 重试下载；
  本地 key 但文件缺失 → 按 `source_comic_id` 回源重抓 `cover_url` 再落盘；健康/无法修复的跳过。
  返回 `{checked, healed, failed, skipped}`；由管理台「触发转存」后**自动执行**（无需单独按钮）。
- `ensure_cover_local` 是单部作品的封面落盘原语（同步链路每轮幂等调用）；`heal_covers` 是
  面向全库的批量自愈编排；
- 生产环境实现 OSS/COS 版的 `ImageStore` 替换 `LocalImageStore` 即可。

## 采集时间窗口（`since`，增量 vs 全量）

`incremental_sync` / `full_sync` 均支持手动指定起始日期 `since`（ISO 8601），语义如下：

- **增量（`--mode incremental`，默认）**：`since` 不填时自动取该源**上次同步时间**（`Storage.get_last_sync_time` 查 `sync_log.finished_at`，无记录返回 None），即采集 `[上次同步, 现在]` 窗口；手动填 `since` 则**优先于水位**，用于回补（上次同步之后漏掉/被跳过的时间段）或前移窗口。
- **全量（`--mode full`）**：默认 `since=None` **无时间窗口**，扫描列表接口能返回的全部（不限时间）；手动填 `since` 时同样按 `[since, 现在]` 过滤。
- **手动指定优先于水位**：`run --source xxx --mode incremental --since 2026-09-01` 即采集 9 月 1 日至今（而不是从上次同步开始）。
- 源站按各自时间字段过滤（再漫画 `last_updatetime` Unix 时间戳；瓜子列表无时间字段，用 date 参数近似）；首采（无水位）默认收当天全部。
- 采集管理控制台（`/#/admin`，见 api-service README）在页面上暴露上述参数，无需手敲命令行：**采集**面板可填 `mode` / `since` / `limit`；**懒转存**面板只填 `since` / `until`（**已无数量输入**，语义就是「把窗口内所有未转存页全部转掉」）；页面顶部另有**全库「失效巡检」**面板（不随源复制），同样填 `since` / `until`，语义 = 上述转存 + **全表**校验已转存对象（缺失自动恢复）。

## 合规说明（务必阅读）

本实现是**架构骨架**：`HttpFetcher` 的限速、UA 池、指数退避均在合规框架内。
实际对接任何目标站前，必须（见架构方案 §6.2）：

- 确认该站允许抓取（robots.txt / 服务条款）或已获授权；
- **仅收录已授权、开放版权（CC）或公共领域内容**，未授权内容建黑名单过滤；
- 不绕过登录、验证码等技术壁垒；接入内容审核与版权存证（`sync_log`）。
