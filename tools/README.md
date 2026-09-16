# tools —— 一次性数据迁移 / 运维脚本

**手动执行、跑完即弃**的脚本（Python）。不属于日常运行链路，服务启动时**不会**自动调用。

与 [`../scripts/`](../scripts/README.md) 的区别：`scripts/` 是"把环境/服务跑起来"，本目录是
"对已有数据做一次性结构或内容迁移"。

| 脚本 | 作用 | 幂等性 |
|---|---|---|
| `migrate_comic_tag_normalize.py` | 标签规范化迁移：旧 `comic_tag(comic_id, tag)` → `tag(id,name)` 字典表 + `comic_tag(comic_id, tag_id)` 关联表 | 是（保留 `comic_tag_old` 备份后重建） |
| `backfill_comic_tag.py` | 按分隔符拆分 `comic.category`，回填标签到 `tag` + `comic_tag`（`category` 原串不动） | 是（先清该漫画旧关联再插） |
| `normalize_tags.py` | **标签归一化**：把库内已有标签按 `data/tag_synonyms.json` 合并为统一中文规范名（跨源跨语言同义合并；含**繁转简**，如 `格鬥`→`动作`） | 是（可重跑；执行前完整备份 `tag`/`comic_tag` 到 `backup/`） |
| `rebuild_fingerprint.py` | **重建 `comic.fingerprint`**：归一化规则变化（如加入繁转简）后，把历史行指纹按当前规则对齐，否则新采集的简体写法会与库里的繁体写法各占一行 | 是（只更新变了的行，可重跑；执行前把旧指纹写成可反向执行的 SQL 到 `backup/`） |
| `add_log_table.py` | **补 `log_record` 表**（运行日志逐条落库；DDL 从 `mysql_schema.sql` 抠出，不重抄） | 是（`CREATE TABLE IF NOT EXISTS`，可重跑；回滚 = `DROP TABLE log_record`） |
| `add_perf_indexes.py` | **补齐性能索引**：给已有库补上 `comic.idx_comic_sync` / `page.idx_page_cached`（新库由 `mysql_schema.sql` 直接带上） | 是（幂等可重跑；只加索引不动数据，回滚 = `DROP INDEX`） |

运行方式：

```bash
cd crawler-service && .venv/Scripts/python.exe ../tools/migrate_comic_tag_normalize.py
cd crawler-service && .venv/Scripts/python.exe ../tools/backfill_comic_tag.py
cd crawler-service && .venv/Scripts/python.exe ../tools/normalize_tags.py
cd crawler-service && .venv/Scripts/python.exe ../tools/rebuild_fingerprint.py
```

> 归一化口径变化时这两个一起跑：`rebuild_fingerprint.py` 管作品判重（指纹），
> `normalize_tags.py` 管标签（`tag` / `comic_tag`）。先备份库，再跑，最后复跑确认幂等。

⚠️ 注意事项：

- 都会**写数据库**，执行前先备份（`mysqldump`，产物放 `backup/`，该目录已 gitignore）。
- 新脚本按此约定命名与放置：**一次性的入库/改结构** → 本目录；**重复可跑的运维/巡检** → 写成
  `crawler-service` 的 CLI 子命令，不要放这里。
