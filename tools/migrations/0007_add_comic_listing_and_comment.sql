-- 0007_add_comic_listing_and_comment.sql —— 加「作品上下架」与「评论区」所需的列 / 表
--
-- 背景（2026-10-09 两个需求）：
--   1. 作品上下架 —— comic.listed（1=上架 / 0=下架；下架后前台不可见、详情 404，数据保留、采集照旧）；
--   2. 评论区 —— comic.comment_enabled（单作品开关）+ comment 表（评论正文，只收登录用户）
--      + app_setting 表（全站键值配置，放全站评论总开关）。
-- 幂等性：只跑一次 —— 由执行器（tools/migrate.sh）的记录表保证；本文件不做重复保护。
-- 回滚（**会丢评论数据**，仅限本地/测试）：
--   DROP TABLE IF EXISTS comment;
--   DROP TABLE IF EXISTS app_setting;
--   ALTER TABLE comic DROP INDEX idx_comic_listed_sync;
--   ALTER TABLE comic DROP COLUMN listed, DROP COLUMN comment_enabled;

ALTER TABLE comic ADD COLUMN listed TINYINT NOT NULL DEFAULT 1 AFTER addtime;
ALTER TABLE comic ADD COLUMN comment_enabled TINYINT NOT NULL DEFAULT 1 AFTER listed;
ALTER TABLE comic ADD INDEX idx_comic_listed_sync (listed, sync_time);

CREATE TABLE IF NOT EXISTS comment (
    id INT AUTO_INCREMENT PRIMARY KEY COMMENT '自增主键',
    comic_id INT NOT NULL COMMENT '作品 id（comic.id）',
    user_id VARCHAR(64) NOT NULL COMMENT '作者账号 id（字符串列，与 favorite/history 同型）',
    content VARCHAR(500) NOT NULL COMMENT '评论内容（≤500 字）',
    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP COMMENT '发表时间',
    KEY idx_comment_comic (comic_id, id),
    KEY idx_comment_user (user_id, created_at),
    CONSTRAINT fk_comment_comic FOREIGN KEY (comic_id) REFERENCES comic(id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_general_ci COMMENT='评论表：漫画详情页评论区（只允许登录用户发表）';

CREATE TABLE IF NOT EXISTS app_setting (
    k VARCHAR(64) NOT NULL PRIMARY KEY COMMENT '配置键（主键）',
    v VARCHAR(255) NOT NULL DEFAULT '' COMMENT '配置值（字符串，由读取方解释）',
    updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP COMMENT '更新时间'
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_general_ci COMMENT='全站级键值配置（目前放 comment_enabled 全站评论总开关）';
