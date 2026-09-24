# comic-crawler 采集服务

漫画聚合平台的采集层：**调度 → 抓取 → 解析 → 判重入库（同源精确）→ 图片懒转存 → 失效巡检 → 同步日志**。
只依赖 `CrawlerAdapter` / `Storage` 两套契约；api-service 会在**进程内**直接调用本包（改完本包必须重启后端），
但**只允许经 `facade.py` 这一个契约面**进入 —— 见下方「对外契约面」。

## 模块架构

分层约定：**通用在外、扩展在里；依赖只能由内向外**，由 `tests/test_layering.py` 断言守卫。

```
crawler-service/
├── src/comic_crawler/
│   ├── cli.py                          # 命令行入口（run / transfer-images / inspect / serve / list / show）
│   ├── facade.py                       # **对外契约面**：api-service 唯一允许 import 的模块（见下节）
│   ├── sources/                        # 源站层：契约在外，各源在里
│   │   ├── base.py · registry.py       #   L1 契约：CrawlerAdapter 抽象 + @register 注册表
│   │   ├── state.py                    #   源开关状态（source_state.json）的**唯一读写归属**
│   │   └── <源名>/                     #   L2 实现：每源一个自包含子包（4 件套）
│   ├── images/                         # 图片层
│   │   └── transfer.py                 #   懒转存 · 读时穿透取图 · 封面落盘
│   ├── scheduling/                     # 编排层：何时跑 / 跑一次做什么
│   │   ├── sync.py · ondemand.py · heal.py · scheduler.py
│   └── http.py                         # HTTP 抓取封装
├── data/                               # 运行时数据（gitignore）：image_store/ 图库 + source_state.json 源开关
└── tests/                              # 单元测试（含分层守卫）
```

> **L0 通用内核已抽到 [`comic-core/`](../comic-core/README.md)（2026-09-24）**：
> `models` · `config` · `paths` · `taxonomy` · `logctx` · `images/store`（图库读写）·
> `storage/`（存储契约 + MySQL 实现）整批搬走，由本包与 api-service **共用**（单向依赖：crawler → core）。
> 本包因此只剩上图这些 —— 凡是「采集特有的编排」，凡是「两个服务都要用的基础设施」，边界就在这里。
> ⚠️ `comic-core/paths.py` 推导的 **data 根仍寄居在本目录**（`crawler-service/data`），
> 这是刻意为之：容器把 `/data` bind 的正是它，动了就破坏「本地直跑与 Docker 读写同一批文件」。
> SQL 建表脚本也随之迁到 `comic-core/sql/mysql_schema.sql`。

### 对外契约面（`facade.py`）

**api-service 只允许 `from comic_crawler.facade import ...`**，不得 import 本包的任何子模块
（由 `api-service/tests/test_crawler_boundary.py` 断言守卫）。

- `facade.__all__` 就是契约清单（领域模型 / 源站工厂 / 存储实现 / 编排函数 / 图片读写 / 源开关状态 / 日志上下文）；
- **本包内部随便重构** —— 换模块名、拆文件、改类名 —— 只要契约面的**符号名与签名不变**，api 零改动；
- 因此**改这里的签名 = 破坏性变更**，要当对外接口对待；
- `facade` 与 `cli` 一样在 `tests/test_layering.py` 里豁免分层断言（它的职责就是聚合各层能力）。

### 源站接入契约（`sources/base.py`）

**`CrawlerAdapter` 是新增源站的唯一接入点** —— 业务 / 存储 / 调度层均不感知具体源。

| 成员 | 必选 | 作用 |
|---|---|---|
| `fetch_comic_list(page, since)` | ✓ | 列表页 → 漫画摘要 + `has_next`（翻页由它驱动，`since` 为增量窗口起点） |
| `fetch_comic_detail(comic)` | ✓ | 详情页 → 简介 + 章节列表 |
| `fetch_chapter_pages(detail, chapter)` | ✓ | 章节页 → 分页图片 URL（按 `page_no` 升序） |
| `fetch_source_page_urls(comic_id, chapter_id)` | 可选 | 签名 URL 过期时**现场重拉整章**重新签发（默认不支持） |
| `search_comics(keyword, limit)` | 可选 | 源站关键词搜索，需声明 `capabilities={"search"}` |
| `parse_comic_ref(ref)` | 可选 | 作品链接 / ID → `source_comic_id`，需声明 `capabilities={"ref"}` |
| `image_hosts` | 可选 | 图床域名白名单（转存与穿透都校验，防 SSRF）；**留空 = 不校验** |
| `pre_fetch` / `post_fetch` | 可选 | 每轮抓取前后的钩子（robots 预检 / 释放资源） |

新增源站：`cp -r sources/zaimanhua sources/<新源名>` → 改 `adapter.py` 三个必选方法 → 在该子包
`__init__.py` 声明 `SOURCES`（频率 / 启停**就近维护**）→ 在 `sources/__init__.py` 的 `_SOURCE_PACKAGES` 登记。
**全程只动 `sources/`**。子包 4 件套：`__init__.py`（导出 + `SOURCES`）、`adapter.py`（解析）、
`README.md`（接口 / 请求头 / 限流 / 已知坑）、`fixtures/`（离线样例，可选）。

## 功能与接口

**命令行**（`python -m comic_crawler.cli <子命令>`）

| 子命令 | 作用 |
|---|---|
| `run --source X [--mode incremental\|full] [--since D] [--limit N]` | 采集某源（默认增量；`--limit` 为受控样本） |
| `transfer-images [--since D] [--until D] [--limit N] [--source X]` | 转存窗口内的**未转存页**（默认不限量；`--source` 只转某源） |
| `inspect [--source X] [--since D] [--until D]` | 失效巡检：转存未转存页 + **全表**校验已转存对象 + 丢失恢复 |
| `serve [--source X] [--interval S]` | 常驻定时调度：增量按各源间隔 / 每日全量 / 每小时巡检 |
| `list` · `show` | 列出已注册适配器 · 查看库内数据 |

**按需导入**（`scheduling/ondemand.import_comic`；入口为搜索页「导入并阅读」或 `POST /api/admin/import`）
—— 与采集共用同一套入库逻辑（`sync._upsert_detail`），差别只在驱动方式：

| 环节 | 行为 |
|---|---|
| 详情 | 1 次请求拿书目 + **全部章节** |
| 书目 / 章节 | 写 `comic` 1 行 + 补齐库内缺失的全部章节（判重见下） |
| 页清单 | **一页都不登记** |
| 正文图 | **一张都不下载**（只落封面） |
| 可读性 | **实测探测**（先最新章、再退最老章），任一章取到图即放行；全取不到才拒绝 |

**图片链路**（`images/`）

| 阶段 | 作用 |
|---|---|
| 登记 | 采集 / 导入**不产生 page 行**；用户首次打开某话时由 api-service 调 `ensure_chapter_pages` 登记页清单（只记 `source_url`、`cached_status='未转存'`） |
| 批量转存 | `lazy_transfer`：下载 → 写 `ImageStore` → 回填 `oss_url` + 置 `已转存`；**只处理已登记的页**，并发 2 路 |
| 读时穿透 | `fetch_page_bytes`：本地没有就现场取**这一张**并顺手落盘；签名过期自动重拉。三道约束见「约定」 |
| 巡检 | `inspect_sync`：转存未转存页 + 按 `id` **键集分页**校验全表对象存在性并恢复（不被固定条数截断） |
| 封面 | `ensure_cover_local`（单部落盘原语）/ `heal_covers`（按源、按作品批量自愈） |

## 基础命令

```bash
# 环境：项目自带的 venv（依赖公共内核的 pymysql / cryptography / zhconv 也装在这里）
python -m venv .venv && .venv/Scripts/pip install -r requirements.txt

# ⚠️ 本包与 comic-core 是**两个**本地包，跑之前两个 src 都要在 PYTHONPATH 上：
export PYTHONPATH=src:../comic-core/src        # Windows(PowerShell): $env:PYTHONPATH="src;../comic-core/src"

# 数据库容器（本项目独占实例，宿主 127.0.0.1:3309；连接参数读 deploy/.env，无需手工导出）
docker compose -f ../deploy/docker-compose.yml up -d comic-mysql

# 采集 / 转存 / 巡检 / 定时调度
python -m comic_crawler.cli run --source zaimanhua --limit 3
python -m comic_crawler.cli transfer-images
python -m comic_crawler.cli inspect
python -m comic_crawler.cli serve

# 单测（纯逻辑：不连库、不写临时文件）
python -m unittest discover -s tests -t tests
```

> **为什么要两个 `src`**：`comic_core` 已抽到 `comic-core/`（见上），本包只声明依赖、不重复实现。
> 直跑采集 CLI 时没有 api 那套 `core.bootstrap` 引导，所以得自己给全。
> 若嫌麻烦，改用 editable 装一次即可：`.venv/Scripts/pip install -e ../comic-core -e .`，
> 之后直接 `python -m comic_crawler.cli ...`（不再需要 `PYTHONPATH`）。
> 容器里两个包都由 pip 装进 site-packages（见 `deploy/crawler/Dockerfile`），同样不用设。

> 用容器起库**不需要手工建表**（数据卷首次初始化会执行 `sql/mysql_schema.sql`）；
> 只有连外部 MySQL 才手工建 —— 注意 schema 是纯 DDL，里面**没有 `CREATE DATABASE`**。
> ⚠️ 该脚本已随存储域迁到 **`comic-core/sql/mysql_schema.sql`**。

## 约定

**存储与判重**
- 唯一存储是 MySQL（`MySQLStorage`），`Storage` / `UserStore` 抽象作为契约保留；取连接走**共享连接池**（`storage/mysql/_pool.py`，每进程上限 20）。
- **判重只看 `(source, source_comic_id)`**（`uk_source_comic`），重复抓取幂等覆盖；**跨源不合并** —— 同一部作品在别的源收过就是另一行（译本进度往往不同，合并会丢信息）。
- `fingerprint`（标题归一 + 作者）**只写不判重**，留作「这几行可能是同一部作品」的观测标记。
- **时间列一律 `DATETIME`**（naive 本机时间）；容器**必须配时区**（`COMIC_TZ`，默认 `Asia/Shanghai`），否则存进去的比北京时间早 8 小时。
- 每张表都有自增代理主键 `id`；**业务唯一性用 `UNIQUE KEY` 单独表达** —— 幂等写入依赖的是这些唯一键，不是主键。
- `log_record` 是「**真下载**」的**流水**而非状态快照（封面文件已在本地时不写日志）；任务级统计另见 `sync_log`。
- **源开关状态归采集层**：`data/source_state.json` 的路径与读写都在 `sources/state.py`（env `COMIC_STATE_FILE` 覆盖，**仅绝对路径生效**），
  经门面 `load_source_state` / `save_source_state` 暴露；api 侧只调门面，不感知该文件。

**采集与章节**
- **增量 = 时间窗口**：`since` 不填则取该源上次同步时间（`sync_log.finished_at`）为水位，窗口 `[水位, now]`；**手动 `since` 优先于水位**；全量默认无窗口。
- **章节采样**：首采与增量都**补齐库内缺失的全部章节**（含历史空洞）。
- **页清单一律不在入库时登记**：逐话请求源站页清单既慢又易触发风控，留到用户真正打开那一话。
- **接口不返回章节页数**：源站只有单话接口能给页数、没有批量途径，故 `get_chapters` 不做 `COUNT(page)`。
- **读一张图只查一行**：`get_page_context(chapter_id, page_no)`（含 `total_pages` 标量子查询）——不要为拿总页数去 `get_pages()` 拉整章。
- **读时穿透的三道约束**：出站并发上限 4 / 同一页并发只下一次 / 失败进 60s 负缓存（闸门排队超时**不写**负缓存 —— 拥挤不是"这一页坏了"）。

**标签**
- 归一发生在**写入侧**（`taxonomy.py` + `data/tag_synonyms.json` 的 `canonical_tag`），查询侧零翻译；未命中的标签**保持原文，不猜测、不丢弃**。
- **刻意不做**：机器翻译（错译会被固化成"规范名"）、形态类（`Web Comic` / `Full Color` / `Long Strip` …）、更新季、敏感标签。
- 维护：往 `data/tag_synonyms.json` 加一行，重跑 `tools/normalize_tags.py`（幂等；执行前自动导出备份到 `backup/`）。

**图片与封面**
- 图库根**唯一真源** `images.store.default_store_root()`（`COMIC_IMAGE_ROOT` → `<服务根>/data/image_store`）——**读写两端共用同一函数**，不随进程 cwd 漂移。
- DB 只存**图库内相对 key**（`covers/26.jpg`、`comic/26/34/001.jpg`），不存外链 / 绝对路径。
- 封面落盘判据只看「**文件在不在**」，故普通自愈**修不到错图**；要修「文件在、内容错」用 `force=True`（管理台「封面自愈 · 指定作品」）。
- 换一个 `ImageStore` 实现即可接 OSS / COS（生产用），上层无需改动。

**合规（务必阅读）**
- 确认目标站允许抓取（robots.txt / 服务条款）或已获授权；**仅收录已授权 / 开放版权（CC）/ 公共领域内容**。
- **不绕过登录、验证码等技术壁垒**；限速 / UA 池 / 指数退避已在 `http.py` 内实现；保留来源链（`sync_log`）以便定向清理。

---

> 各源站的接口路径 / 请求头 / 限流与已知坑见 `sources/<源名>/README.md`；
> 修复过程与验证记录写在 `.workbuddy/memory/YYYY-MM-DD.md`，不进本文件。
