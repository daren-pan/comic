-- 0003_drop_fingerprint_unique.sql —— 去掉 comic.fingerprint 的唯一约束，改成普通索引
--
-- 背景（2026-09-16 决策：跨源不再合并）：判重只看 (source, source_comic_id)；
--   同一部作品在别的源收录时要能作为新行插入，而 uk_fingerprint 唯一约束会直接让 INSERT 报重复键。
--   fingerprint 保留为"这几行可能是同一部作品"的观测标记（归一化标题 + 作者），不参与判重。
-- 幂等性：只跑一次 —— 由执行器（tools/migrate.sh）的记录表保证；本文件不做重复保护。
-- ⚠️ 回滚有限制：约束去掉后库内可能已出现同指纹多行，重建 UNIQUE 会因重复值失败（须先人工处理）：
--   ALTER TABLE comic DROP INDEX idx_comic_fingerprint, ADD UNIQUE KEY uk_fingerprint (fingerprint);

ALTER TABLE comic DROP INDEX uk_fingerprint;
ALTER TABLE comic ADD INDEX idx_comic_fingerprint (fingerprint);
