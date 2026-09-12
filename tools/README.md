# tools —— 一次性数据迁移 / 运维脚本

**手动执行、跑完即弃**的脚本（Python）。不属于日常运行链路，服务启动时**不会**自动调用。

与 [`../scripts/`](../scripts/README.md) 的区别：`scripts/` 是"把环境/服务跑起来"，本目录是
"对已有数据做一次性结构或内容迁移"。

| 脚本 | 作用 | 幂等性 |
|---|---|---|
| `migrate_comic_tag_normalize.py` | 标签规范化迁移：旧 `comic_tag(comic_id, tag)` → `tag(id,name)` 字典表 + `comic_tag(comic_id, tag_id)` 关联表 | 是（保留 `comic_tag_old` 备份后重建） |
| `backfill_comic_tag.py` | 按分隔符拆分 `comic.category`，回填标签到 `tag` + `comic_tag`（`category` 原串不动） | 是（先清该漫画旧关联再插） |
| `normalize_tags.py` | **标签归一化**：把库内已有标签按 `data/tag_synonyms.json` 合并为统一中文规范名（跨源跨语言同义合并） | 是（可重跑；执行前完整备份 `tag`/`comic_tag` 到 `backup/`） |

运行方式：

```bash
cd crawler-service && .venv/Scripts/python.exe ../tools/migrate_comic_tag_normalize.py
cd crawler-service && .venv/Scripts/python.exe ../tools/backfill_comic_tag.py
```

⚠️ 注意事项：

- 都会**写数据库**，执行前先备份（`mysqldump`，产物放 `backup/`，该目录已 gitignore）。
- 新脚本按此约定命名与放置：**一次性的入库/改结构** → 本目录；**重复可跑的运维/巡检** → 写成
  `crawler-service` 的 CLI 子命令，不要放这里。
