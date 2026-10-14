-- 0006_add_message_table.sql —— 补消息中心两张表 / 三个新列，去掉废弃的 read_at
--
-- 背景（2026-10-06：消息中心从"仅管理员 + 已读全局一份"改成"面向所有登录用户 + 已读按账号各一份"）：
--   · message 补 to_user_id / min_role（收件范围：定向某人 / 最低角色要求）、params（入参快照）；
--   · 新表 message_read（已读记账，一行 = 某账号读过某条消息）；
--   · 去掉 message.read_at（被 message_read 取代）。
-- 幂等性：只跑一次 —— 由执行器（tools/migrate.sh）的记录表保证；本文件不做重复保护。
--   ⚠️ 本迁移假定库中**已有 message 表**（旧结构）：CREATE 跳过、ALTER 生效。
-- 回滚：DROP TABLE message_read;
--   ALTER TABLE message DROP COLUMN to_user_id, DROP COLUMN min_role, DROP COLUMN params, ADD COLUMN read_at DATETIME NULL;

CREATE TABLE IF NOT EXISTS message (
    id INT AUTO_INCREMENT PRIMARY KEY COMMENT '自增主键',
    kind VARCHAR(16) NOT NULL DEFAULT '' COMMENT '消息类型（任务消息=任务类型；其余写者自定义）',
    level VARCHAR(8) NOT NULL DEFAULT 'info' COMMENT '级别：info / warn / error（同时承载任务成败）',
    title VARCHAR(255) NOT NULL DEFAULT '' COMMENT '标题',
    body TEXT COMMENT '正文',
    params JSON NULL COMMENT '入参快照（JSON，消息自带一份，不依赖任务表）',
    task_id VARCHAR(64) NOT NULL DEFAULT '' COMMENT '关联任务号（admin_task.task_id）',
    source VARCHAR(64) NOT NULL DEFAULT '' COMMENT '数据源（任务类消息）',
    user_id INT NULL COMMENT '触发人 id（系统/定时为空）',
    username VARCHAR(64) NOT NULL DEFAULT '' COMMENT '触发人名（冗余）',
    to_user_id INT NULL COMMENT '定向收件人 id（NULL = 不限人）',
    min_role VARCHAR(16) NOT NULL DEFAULT '' COMMENT '最低可见角色（空 = 所有登录用户，admin = 管理员及以上）',
    created_at DATETIME NOT NULL COMMENT '创建时间',
    KEY idx_msg_created (created_at),
    KEY idx_msg_kind_created (kind, created_at),
    KEY idx_msg_task (task_id),
    KEY idx_msg_to_user (to_user_id, created_at),
    KEY idx_msg_role_created (min_role, created_at)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_general_ci COMMENT='消息中心：平台级消息流（顶栏铃铛 / 消息页数据源）';

CREATE TABLE IF NOT EXISTS message_read (
    id INT AUTO_INCREMENT PRIMARY KEY COMMENT '自增主键',
    message_id INT NOT NULL COMMENT '消息 id（message.id）',
    user_id INT NOT NULL COMMENT '账号 id',
    read_at DATETIME NOT NULL COMMENT '读取时间',
    UNIQUE KEY uk_msg_read (message_id, user_id),
    KEY idx_msg_read_user (user_id, read_at)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_general_ci COMMENT='消息已读记账：一行 = 某账号读过某条消息（按账号各一份）';

-- 老库的 message 建得早，缺下面几个列 / 多一个废弃列
ALTER TABLE message ADD COLUMN to_user_id INT NULL AFTER username;
ALTER TABLE message ADD COLUMN min_role VARCHAR(16) NOT NULL DEFAULT '' AFTER to_user_id;
ALTER TABLE message ADD COLUMN params JSON NULL AFTER body;
ALTER TABLE message DROP COLUMN read_at;
