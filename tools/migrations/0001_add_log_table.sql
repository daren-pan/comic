-- 0001_add_log_table.sql —— 补 log_record 表（运行日志逐条落库）
--
-- 背景：运行日志原先只写文件 logs/api.log，管理台靠"读文件末尾"展示（前端每 4 秒轮询）；
--       改为落库后，管理台「日志查询」页按级别 / 源站 / 作品 / 章节 / 任务 / 关键字 / 时间窗筛选。
-- 幂等性：只跑一次 —— 由执行器（tools/migrate.sh）的记录表保证；本文件不做重复保护。
-- 回滚：DROP TABLE log_record;

CREATE TABLE IF NOT EXISTS log_record (
    id INT AUTO_INCREMENT PRIMARY KEY COMMENT '自增主键',
    created_at DATETIME NOT NULL COMMENT '日志时间（写入进程本机时间，容器须配 TZ）',
    level VARCHAR(8) NOT NULL DEFAULT '' COMMENT '级别（INFO / WARNING / ERROR…）',
    logger VARCHAR(64) NOT NULL DEFAULT '' COMMENT '记录器名',
    message TEXT COMMENT '日志正文',
    task_id VARCHAR(64) NOT NULL DEFAULT '' COMMENT '所属任务号（admin_task.task_id）',
    task_type VARCHAR(16) NOT NULL DEFAULT '' COMMENT '任务类型',
    exc_type VARCHAR(64) NOT NULL DEFAULT '' COMMENT '异常类型（有异常时）',
    exc_text TEXT COMMENT '异常堆栈',
    source VARCHAR(64) NOT NULL DEFAULT '' COMMENT '数据源',
    comic_id INT NULL COMMENT '作品 id',
    comic_title VARCHAR(255) NOT NULL DEFAULT '' COMMENT '作品名（冗余，便于直接阅读）',
    chapter_id INT NULL COMMENT '章节 id',
    chapter_title VARCHAR(255) NOT NULL DEFAULT '' COMMENT '章节标题',
    endpoint VARCHAR(255) NOT NULL DEFAULT '' COMMENT '接口路径（读图类日志）',
    pages INT NULL COMMENT '页数（转存类日志）',
    reason VARCHAR(255) NOT NULL DEFAULT '' COMMENT '原因 / 说明',
    event VARCHAR(32) NOT NULL DEFAULT '' COMMENT '事件类型（日志页筛选用）',
    KEY idx_log_created (created_at),
    KEY idx_log_level_created (level, created_at),
    KEY idx_log_source_created (source, created_at),
    KEY idx_log_task (task_id),
    KEY idx_log_comic (comic_id, created_at)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_general_ci COMMENT='运行日志：逐条落库（管理台「运行日志」页数据源）';
