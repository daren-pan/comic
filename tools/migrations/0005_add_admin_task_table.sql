-- 0005_add_admin_task_table.sql —— 补 admin_task 表（管理台后台任务落库）
--
-- 背景：管理台"后台任务"以前是进程内 dict（api 重启任务就没了、也答不出"是谁点的"）；
--       落库后重启不丢（残留 running 由服务启动时标成中断）、与触发账号绑定、入参可复盘。
-- 幂等性：只跑一次 —— 由执行器（tools/migrate.sh）的记录表保证；本文件不做重复保护。
-- 回滚：DROP TABLE admin_task;

CREATE TABLE IF NOT EXISTS admin_task (
    id INT AUTO_INCREMENT PRIMARY KEY COMMENT '自增主键',
    task_id VARCHAR(64) NOT NULL COMMENT '任务号（唯一，形如 sync-1-aaa；log_record 按它关联）',
    task_type VARCHAR(16) NOT NULL DEFAULT '' COMMENT '任务类型（sync / transfer / inspect / import / heal / schedule）',
    status VARCHAR(16) NOT NULL DEFAULT 'running' COMMENT '状态：running / done / failed',
    message VARCHAR(500) NOT NULL DEFAULT '' COMMENT '状态说明（一句话）',
    result JSON NULL COMMENT '结果 payload（JSON，给前端展示）',
    params JSON NULL COMMENT '入参快照（JSON，复盘「当时点的是什么」）',
    user_id INT NULL COMMENT '触发账号 id（NULL = 系统/定时）',
    username VARCHAR(64) NOT NULL DEFAULT '' COMMENT '触发账号名（冗余，账号删改后仍可读）',
    started_at DATETIME NOT NULL COMMENT '开始时间',
    finished_at DATETIME NULL COMMENT '结束时间',
    UNIQUE KEY uk_task_id (task_id),
    KEY idx_task_started (started_at),
    KEY idx_task_user_started (user_id, started_at),
    KEY idx_task_status (status)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_general_ci COMMENT='管理台后台任务：一次手动触发或定时轮次 = 一行（状态/归属/入参快照，重启不丢）';
