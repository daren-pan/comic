-- 0009_migrate_comic_status.sql —— comic.status 历史写法归一（连载→连载中 / 完结→已完结）
--
-- 背景：四个源的适配器此前各写一套状态映射，库里同一概念存成三种写法（实测：连载 29 / 连载中 23 / 完结 2），
--   且接口层曾用白名单静默兜底，导致已完结的作品被强制显示成"连载中"。归一后各源适配器统一调
--   comic_core.status.normalize_status；本迁移把**历史存量**对齐到规范值（连载中 / 已完结 / 休载 / 已取消）。
-- 幂等性：只跑一次 —— 由执行器（tools/migrate.sh）的记录表保证；UPDATE 本身也天然幂等（改过就 0 行）。
-- 回滚：无需（无法区分"本来就是规范值"与"被迁移过"；如需还原请从备份恢复）。
--
-- 别名表与 comic_core.status._ALIASES 一致（含繁体写法）；匹配前 LOWER(TRIM())，
-- 空串按"连载中"处理（与 normalize_status 的默认语义一致）。规范值本身不在此列、不会被重复更新。

UPDATE comic SET status = '连载中' WHERE status = '' OR LOWER(TRIM(status)) IN ('连载', '連載', '連載中', 'ongoing');
UPDATE comic SET status = '已完结' WHERE LOWER(TRIM(status)) IN ('完结', '完結', '已完結', 'completed', 'complete');
UPDATE comic SET status = '休载'   WHERE LOWER(TRIM(status)) IN ('休載', 'hiatus');
UPDATE comic SET status = '已取消' WHERE LOWER(TRIM(status)) IN ('cancelled', 'canceled');
