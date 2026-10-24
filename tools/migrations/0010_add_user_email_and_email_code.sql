-- 0010_add_user_email_and_email_code.sql —— 给 user 表加绑定邮箱 + 改密时刻，并新建 email_code 表
--
-- 背景：「忘记密码」改用**邮箱验证码**自助重置（2026-10-24 需求）。为此需要三样东西：
--   ① `user.email`：账号的找回通道（NULL = 未绑定）。**必须可 NULL** —— `uk_email` 不比较 NULL
--      （任意多行未绑定都合法），而 `''` 是普通值，第二行 `''` 直接撞唯一键报 1062，
--      上线即挡死所有未绑定用户。代码里空串一律显式转 NULL。
--   ② `user.password_changed_at`：改密 / 重置时刷新，`get_current_user` 据此让**更早签发的
--      token 立即失效（JWT 无状态、项目里没有 token 吊销表）。NULL = 从未改过 → 跳过判定，
--      所以存量 token 不会被本次上线踢下线。
--   ③ `email_code`：验证码的**持久**存储（60 秒冷却 / 每小时配额 / 失败次数 / 单次消费）。
--      不放进程内存：重启或多 worker 会丢，表现为「刚收到的码立刻无效」；本项目也没有 Redis。
--      **无论邮箱是否已注册都落一行** —— 让冷却与配额对两种情况完全一致，否则就成了邮箱枚举侧信道。
--
-- 幂等性：只跑一次 —— 由执行器（tools/migrate.sh）的记录表保证；本文件不做重复保护。
--   ⚠️ 全新库**一条迁移都不跑**（`mysql_schema.sql` 已建全表），所以上面这些 DDL 必须与
--   `comic-core/sql/mysql_schema.sql` 的本体**同批一致**，否则新装环境直接缺列缺表。
--
-- 回滚（⚠️ 先备份：`mysqldump comic > backup.sql`；第 ② 步会丢数据）：
--   DROP TABLE IF EXISTS email_code;              -- ① 只丢一次性数据，不影响业务
--   ALTER TABLE user DROP INDEX uk_email;         -- ② ⚠️ 丢全部已绑定邮箱 + 改密时刻
--   ALTER TABLE user DROP COLUMN password_changed_at;
--   ALTER TABLE user DROP COLUMN email;
--   ALTER TABLE user COMMENT = '用户表（角色三档：superadmin / admin / user）';
-- 回滚边界：① 失去找回密码能力（需重新绑定）；② 「重置后旧 token 失效」能力消失；
--   ③ 已经重置出来的新密码**不回滚**（属用户业务数据，要回到改动前只能从备份恢复）。

-- ---- ① user 加两列（位置：role 之后、created_at 之前）+ 邮箱唯一键 + 表注释 ----
ALTER TABLE user ADD COLUMN email VARCHAR(128) NULL DEFAULT NULL COMMENT '绑定邮箱（找回密码用；NULL = 未绑定，同一邮箱全库唯一）' AFTER role;

-- 邮箱全库唯一：既是「找回密码」的定位方式（get_user_by_email 走它），
-- 也兜住并发绑定同一邮箱（两账号抢写 → 1062 → 接口转 409）。
-- 排序规则 utf8mb4_general_ci 下 A@x.com / a@x.com 视为重复；代码仍统一 strip().lower() 后写入。
-- 现有行全是 NULL，唯一性检查必过，秒级完成。
ALTER TABLE user ADD UNIQUE KEY uk_email (email);

-- 密码最近修改时刻：不加索引 —— 只在拿到整行后做一次内存比较，没有按它查询的路径。
ALTER TABLE user ADD COLUMN password_changed_at DATETIME NULL DEFAULT NULL COMMENT '密码最近修改时刻（改密 / 重置时刷新；旧 token 据此失效，NULL = 从未改过）' AFTER email;

ALTER TABLE user COMMENT = '用户表（角色三档 + 可绑定邮箱用于找回密码）';

-- ---- ② 新建 email_code（一行 = 一次发码请求；三条二级索引覆盖全部查询路径）----
-- 外键：**刻意不建** —— 账号改绑 / 删号后这些行仍需按发码记录限流，外键会阻止历史行保留。
CREATE TABLE IF NOT EXISTS email_code (
    id INT AUTO_INCREMENT COMMENT '自增主键',
    email VARCHAR(128) NOT NULL COMMENT '收件邮箱（小写归一；无论是否已注册都落行 —— 让冷却/配额对「已注册」与「未注册」完全一致，避免邮箱枚举）',
    purpose VARCHAR(16) NOT NULL DEFAULT 'reset' COMMENT '用途：reset 找回密码 / bind 绑定邮箱（两种用途的码互不干扰）',
    code_hash CHAR(64) NOT NULL COMMENT '验证码的 HMAC-SHA256 十六进制（密钥复用 COMIC_JWT_SECRET；不存明文，库泄露也无法离线爆破 6 位码）',
    attempts TINYINT NOT NULL DEFAULT 0 COMMENT '已校验失败次数（达到 5 即整行作废，此后正确码也不接受）',
    req_ip VARCHAR(64) NOT NULL DEFAULT '' COMMENT '申请来源 IP（每 IP 每小时配额用；反代下取 X-Forwarded-For 首段，空串 = 取不到）',
    expires_at DATETIME NOT NULL COMMENT '过期时刻（发放时刻 + 10 分钟）',
    consumed_at DATETIME NULL COMMENT '消费/作废时刻（非空 = 不可再用：已成功使用 / 被新码顶掉 / 次数超限 三种情形都写它）',
    created_at DATETIME NOT NULL COMMENT '发放时刻（60 秒重发冷却、小时配额、24 小时垃圾清理都基于此列）',
    PRIMARY KEY (id),
    -- 冷却 / 每邮箱小时配额 / 取最新码：一条索引同时服务这三条查询
    KEY idx_code_lookup (email, purpose, created_at),
    -- 每 IP 小时配额
    KEY idx_code_ip (req_ip, created_at),
    -- 24h 垃圾行清理
    KEY idx_code_created (created_at)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_general_ci COMMENT='邮箱验证码：一行 = 一次发码请求（找回密码 / 绑定邮箱共用；单次有效、带次数与配额上限）';

-- ---- ③ 回滚 SQL（**不要随迁移执行**，运维手工用；见文件头「回滚」段）----
-- DROP TABLE IF EXISTS email_code;
-- ALTER TABLE user DROP INDEX uk_email;
-- ALTER TABLE user DROP COLUMN password_changed_at;
-- ALTER TABLE user DROP COLUMN email;
-- ALTER TABLE user COMMENT = '用户表（角色三档：superadmin / admin / user）';
