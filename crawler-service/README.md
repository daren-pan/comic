# comic-crawler 采集服务（骨架实现）

漫画聚合平台（架构方案见 `../漫画聚合网站_架构设计方案.md`）的采集层落地代码。
演示完整链路：**调度 → 抓取 → 解析 → 指纹去重 → 入库 → 图片懒转存 → 失效巡检 → 同步日志**。

## 目录结构

```
crawler-service/
├── src/comic_crawler/
│   ├── adapter/
│   │   ├── base.py            # CrawlerAdapter 抽象接口（新增源站的唯一接入点）
│   │   ├── registry.py        # 适配器注册表（@register 装饰器）
│   │   ├── demo_source.py     # 示例源站 A 适配器（XPath 解析真实 HTML）
│   │   └── demo_source_b.py   # 示例源站 B（继承复用，验证跨站合并）
│   ├── http.py                # 抓取客户端：UA 池 / 随机延迟 / 指数退避 / 代理池预留
│   ├── fingerprint.py         # 标题归一化 + 跨站指纹（跨源去重核心）
│   ├── models.py              # 领域模型：Comic/Chapter/Page/ListResult/SyncStats
│   ├── storage.py             # Storage 抽象 + SQLite 实现（表结构与 MySQL 版一致）
│   ├── mysql_storage.py       # MySQL 实现（MySQLStorage + MySQLUserStore，接口与 SQLite 版一致）
│   ├── migrate.py             # SQLite → MySQL 数据迁移工具
│   ├── image_store.py         # ImageStore 抽象 + 本地模拟 OSS（可替换为 OSS/COS）
│   ├── image_service.py       # 图片懒转存（未转存 → 下载 → 上传 → 状态机更新）
│   ├── scheduler.py           # 增量 / 全量 / 失效巡检调度
│   ├── config.py              # 源站与限速配置
│   └── cli.py                 # 命令行入口
├── fixtures/                  # 模拟源站 HTML（离线可跑）
├── tests/                     # 单元测试
└── requirements.txt
```

## 快速开始

```bash
# 1. 创建虚拟环境并安装依赖
python -m venv .venv
.venv/Scripts/pip install -r requirements.txt     # Windows
# .venv/bin/pip install -r requirements.txt       # macOS/Linux

# 2. 增量同步（源站 A：3 部漫画）
PYTHONPATH=src python -m comic_crawler.cli run --source demo_source

# 3. 增量同步（源站 B：含与 A 重复的"海贼王（重置版）"，验证跨站合并）
PYTHONPATH=src python -m comic_crawler.cli run --source demo_source_b
#    预期：库内 4 部（而不是 5），重复作品被指纹合并

# 4. 图片懒转存（模拟用户阅读触发的按需转存）
PYTHONPATH=src python -m comic_crawler.cli transfer-images

# 5. 失效巡检（转存未转存页 + 校验已转存对象 + 恢复丢失）
PYTHONPATH=src python -m comic_crawler.cli inspect

# 6. 查看库内数据 / 列出已注册适配器
PYTHONPATH=src python -m comic_crawler.cli show
PYTHONPATH=src python -m comic_crawler.cli list

# 7. 跑单元测试（13 个用例，含 MySQL 集成测试）
PYTHONPATH=src python -m unittest discover -s tests -v

# 8. 真实源站同步（Pepper & Carrot，CC-BY 4.0 开源授权）
PYTHONPATH=src python -m comic_crawler.cli run --source peppercarrot
#    - 站点结构为"1 部漫画 + episode 即章节"，默认收录最新 10 话
#      （调整 adapter/pepper_source.py 的 MAX_EPISODES 即全量收录）；
#    - 已核对 robots.txt：仅禁 /cache/、/extras/temp/，正文图取官方 low-res 版；
#    - 入库后执行懒转存即可下载真实漫画图。
PYTHONPATH=src python -m comic_crawler.cli transfer-images

# 9. 定时调度守护（增量轮询 / 每日全量 / 失效巡检，Ctrl+C 退出）
#    - 增量间隔取 config.py SOURCES 各源 crawl_interval_seconds（默认 15~30 分钟）
#    - 每日凌晨 3 点后每源跑一次全量；失效巡检每小时一次
#    - --source 可只调度指定源；--interval 调整轮询检查粒度（默认 30s）
COMIC_DB_TYPE=mysql PYTHONPATH=src python -m comic_crawler.cli serve
```

## 切换 MySQL（生产存储）

采集服务与 API 服务均支持 `COMIC_DB_TYPE=mysql` 环境变量切换存储实现，
业务代码零改动（架构方案 §3.1「抽象可替换」的落地）。

```bash
# 0. 前置：本机 MySQL 可用（默认连 127.0.0.1:3307，兼容 RuoYi-Cloud 的 docker mysql）
#    连接参数可用环境变量覆盖：
#    COMIC_MYSQL_HOST / COMIC_MYSQL_PORT / COMIC_MYSQL_USER / COMIC_MYSQL_PASSWORD / COMIC_MYSQL_DB

# 1. 建库建表（comic 库 + 6 张表，utf8mb4）
mysql -h127.0.0.1 -P3307 -uroot -p -e "CREATE DATABASE comic DEFAULT CHARACTER SET utf8mb4;"
mysql -h127.0.0.1 -P3307 -uroot -p comic < sql/mysql_schema.sql

# 2. 迁移已有数据（从 SQLite 全量导入，保留 id 保证外键一致）
PYTHONPATH=src python -m comic_crawler.migrate --sqlite comic_demo.db

# 3. MySQL 模式下跑采集链路（命令不变，只加环境变量）
COMIC_DB_TYPE=mysql PYTHONPATH=src python -m comic_crawler.cli run --source demo_source
COMIC_DB_TYPE=mysql PYTHONPATH=src python -m comic_crawler.cli transfer-images
COMIC_DB_TYPE=mysql PYTHONPATH=src python -m comic_crawler.cli inspect

# 4. API 服务切 MySQL（前端零改动）
COMIC_DB_TYPE=mysql uvicorn main:app --port 8000   # 在 api-service 目录
```

## 接入一个新源站（两步）

1. **实现适配器**：复制 `adapter/demo_source.py` 为 `adapter/xxx_source.py`，
   把 `base_url` 换成目标域名，按目标站真实 DOM 改写三个方法中的 XPath；
   若结构与现有源相同，直接继承复用（见 `demo_source_b.py`）：

   - `fetch_comic_list(page)` —— 列表页 → 漫画摘要 + has_next；
   - `fetch_comic_detail(comic)` —— 详情页 → 简介 + 章节列表；
   - `fetch_chapter_pages(detail, chapter)` —— 章节页 → 分页图片。

2. **注册**：`adapter/__init__.py` 中 `from . import xxx_source`（装饰器自动注册），
   并在 `config.py` 的 `SOURCES` 添加一行源站配置。

业务层、存储层、调度层无需任何改动 —— 这就是架构方案中「源站可插拔」的落地。
跨站重复作品由 `fingerprint.py` 自动合并（演示：源 A 的「海贼王」与源 B 的
「海贼王（重置版）」命中同一指纹，只保留一条记录）。

## 图片链路（懒转存 + 失效巡检）

- 同步入库时图片只记 `source_url`，`cached_status='未转存'`（不预抓全量图片）；
- `transfer-images` / 阅读服务触发 `lazy_transfer`：下载 → 写入 ImageStore →
  回填 `oss_url`、状态置 `已转存`；
- `inspect` 巡检：转存未转存页 + 校验已转存对象是否存在 + 丢失自动恢复；
- 生产环境实现 OSS/COS 版的 `ImageStore` 替换 `LocalImageStore` 即可。

## 合规说明（务必阅读）

本实现是**架构骨架**：`HttpFetcher` 的限速、UA 池、指数退避均在合规框架内。
实际对接任何目标站前，必须（见架构方案 §6.2）：

- 确认该站允许抓取（robots.txt / 服务条款）或已获授权；
- **仅收录已授权、开放版权（CC）或公共领域内容**，未授权内容建黑名单过滤；
- 不绕过登录、验证码等技术壁垒；接入内容审核与版权存证（`sync_log`）。
