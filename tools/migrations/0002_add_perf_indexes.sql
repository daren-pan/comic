-- 0002_add_perf_indexes.sql —— 补齐两个缺失索引（大数据量下查 / 改走最优路径）
--
-- 背景（2026-09-14 核对现状时发现两处「无索引全表扫 / filesort」）：
--   1. comic.sync_time 无索引 —— 它是列表默认排序键（sort=updated → ORDER BY sync_time DESC）；
--   2. page.cached_status 无索引 —— 转存 / 失效巡检按 cached_status='未转存' 筛，而 page 是全库最大的表；
--      索引带 id 是为配合键集分页（after_id）。
-- 幂等性：只跑一次 —— 由执行器（tools/migrate.sh）的记录表保证；本文件不做重复保护。
-- 回滚（索引与数据无关，随时可删）：
--   ALTER TABLE comic DROP INDEX idx_comic_sync;
--   ALTER TABLE page  DROP INDEX idx_page_cached;

ALTER TABLE comic ADD INDEX idx_comic_sync (sync_time);
ALTER TABLE page  ADD INDEX idx_page_cached (cached_status, id);
