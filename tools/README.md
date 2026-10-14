# tools —— 数据库迁移 / 一次性运维脚本

与 [`../scripts/`](../scripts/README.md) 的区别：`scripts/` 是"把环境/服务跑起来"，本目录是
"对已有数据做迁移 / 运维"。

## 数据库迁移（`migrations/` + `migrate.sh`）

**统一执行器**：`bash tools/migrate.sh`（在仓库根目录跑）—— 只执行**还没跑过**的迁移
（执行记录在 `schema_migration` 表），把 SQL 文件直接喂给 `comic-mysql` 容器里的 mysql 客户端执行
（不依赖 Python、不需要挂载、不改 compose）。

| 命令 | 作用 |
|---|---|
| `bash tools/migrate.sh` | 执行所有未跑过的迁移（结束后自动体检：库表 vs schema） |
| `bash tools/migrate.sh --list` | 只看状态（已执行 / 待执行），不改库 |
| `bash tools/migrate.sh --dry-run` | 预演：列出会跑哪些，不执行 |
| `bash tools/migrate.sh --baseline` | **存量库首次接入**：把现有迁移标记为"已执行"（不执行） |
| `bash tools/migrate.sh --mark <文件名>` | 手动把某个迁移标记为已执行（修复用） |
| `bash tools/migrate.sh --check` | 体检：库里的表 vs schema 声明的表（只读） |

> `deploy/up.sh --migrate` 就是调它；**全新库不需要跑迁移**（`mysql_schema.sql` 已建全表）。

### 存量库首次接入（重要，顺序不能反）

`up.sh --migrate` 走的是**默认执行模式**（跑未执行过的迁移，**不含** baseline）——
存量库必须先**手动**做一次基线登记：

```bash
# ① 一次性：建记录表 + 把现有迁移标记为"已执行"（不执行任何 SQL）
bash tools/migrate.sh --baseline
# ② 之后每次升级：只跑"新加"的迁移
bash deploy/up.sh --migrate
```

- **为什么必须先 baseline**：库里还没有记录表时，执行器会把现有迁移当成"全没跑过"→ 从头跑 →
  已生效的会报错中断（如 0002 加索引报 `Duplicate key name`）；
- **为什么不自动 baseline**："记录表为空"**不等于**"迁移都已生效"—— 一个真缺表的老库若被自动
  登记成"已执行"，补表迁移全被跳过、漏表的后果运行期才炸。baseline 是**人工声明"这个库已经是
  目标态"**，必须人拍板；
- **不确定库的状态时**：**别 baseline** —— 直接 `bash tools/migrate.sh` 跑，遇错停下时人工判断
  （"这条跑过了"→ `bash tools/migrate.sh --mark <文件名>` 登记）再重跑，直到跑通；之后正常。

### 命名规范（新迁移一律沿用，2026-10-14 定）

**`NNNN_<snake_case>.sql`** —— 4 位序号 + 小写下划线描述。例：`0010_add_comic_xxx_column.sql`

- **序号递增、不复用**；已执行过的文件是**历史快照，永不改动**（改了会让各库状态漂移）；
- 一个文件 = 一次变更，可含多条 SQL（按序执行）；
- 文件里写**最朴素的 SQL**（建表 `CREATE TABLE IF NOT EXISTS` / 加列 / 加索引 / `UPDATE`）——
  "只跑一次"由记录表保证，**不必做重复保护**（这也是为什么不再写 Python 迁移脚本：
  MySQL 的改表没有 `IF [NOT] EXISTS` 语法，而"条件判断"那套在记录表面前是多余的）；
- **失败处理**：跑到一半失败 → 不登记 → 修好后重跑；已生效的前半段会报错，人工判断后
  用 `--mark <文件名>` 登记跳过。

### 现有迁移（0001~0009）

| 文件 | 作用 |
|---|---|
| `0001_add_log_table` | 补 `log_record` 表（运行日志逐条落库） |
| `0002_add_perf_indexes` | 补两个性能索引（`comic.idx_comic_sync` / `page.idx_page_cached`） |
| `0003_drop_fingerprint_unique` | 去掉 `comic.fingerprint` 唯一约束（跨源不再合并的前提） |
| `0004_add_user_role` | 加 `user.role` 列 + 定超管（防锁死；转移超管的手工 SQL 见文件尾注释） |
| `0005_add_admin_task_table` | 补 `admin_task` 表（后台任务落库） |
| `0006_add_message_table` | 补消息中心两张表 / 三个新列，去掉废弃的 `read_at` |
| `0007_add_comic_listing_and_comment` | 加「作品上下架」与「评论区」所需列 / 表 |
| `0008_add_table_comments` | 把 schema 的表注释 / 字段注释刷进已有库（由 schema 一次性生成后冻结） |
| `0009_migrate_comic_status` | `comic.status` 历史写法归一（连载→连载中 / 完结→已完结） |

## 其它一次性运维脚本（手动跑，不进迁移链）

| 脚本 | 作用 | 幂等性 |
|---|---|---|
| `normalize_tags.py` | **标签归一化**：把库内已有标签按 `data/tag_synonyms.json` 合并为统一中文规范名（跨源跨语言同义合并；含繁转简） | 是（执行前完整备份 `tag`/`comic_tag` 到 `backup/`） |
| `backfill_comic_tag.py` | 按分隔符拆分 `comic.category`，回填标签到 `tag` + `comic_tag`（`category` 原串不动） | 是（先清该漫画旧关联再插） |
| `migrate_comic_tag_normalize.py` | 标签规范化迁移：旧 `comic_tag(comic_id, tag)` → 字典表 + 关联表 | 是（保留 `comic_tag_old` 备份） |
| `rebuild_fingerprint.py` | 重建 `comic.fingerprint`（观测字段，**不参与判重**），列出"同指纹多行"供人工判断 | 是（执行前把旧指纹写成可反向执行的 SQL 到 `backup/`） |
| `fix_copymanga_page_order.py` | 重排 copymanga 章节的 `page.page_no`（按文件名首位数字升序，排序键复用适配器） | 是（**默认干跑**，加 `--apply` 才落库） |
| `check_schema.py` | 体检：库里的表与 schema 是否一致（只读）—— 执行器 `--check` 已覆盖，此脚本保留备用 | 是（只读；缺表退出码 1） |
| `export_openapi.py` | 导出后端 OpenAPI 快照 `openapi.json`（前端 `npm run gen:api` 生成类型时读它） | 是（只读 + 写文件） |

运行方式（在 comic 仓库根目录）：

```bash
cd crawler-service && .venv/Scripts/python.exe ../tools/normalize_tags.py
cd crawler-service && .venv/Scripts/python.exe ../tools/rebuild_fingerprint.py
cd crawler-service && .venv/Scripts/python.exe ../tools/fix_copymanga_page_order.py
cd crawler-service && .venv/Scripts/python.exe ../tools/check_schema.py      # 体检（只读）
```

⚠️ 注意事项：

- 都会**写数据库**（迁移类），执行前先备份（`mysqldump`，产物放 `backup/`，该目录已 gitignore）；
- 新脚本按此约定放置：**数据库结构 / 数据迁移** → `tools/migrations/NNNN_xxx.sql`（进迁移链，
  由执行器统一跑）；**重复可跑的运维 / 巡检** → 写成 `crawler-service` 的 CLI 子命令，不要放这里。

---

> 踩坑、实测与复盘 → **[NOTES.md](NOTES.md)**（AI 维护）。
