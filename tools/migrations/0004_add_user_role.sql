-- 0004_add_user_role.sql —— 给 user 表加 role 列（管理台鉴权），并把超级管理员定下来
--
-- 背景：管理台 /api/admin/* 原先免登录；改为角色三档制 ——
--   superadmin 超管（管理台 + 日志 + 授权页，**全库唯一**）/ admin 普通管理员（进不了授权页）/ user 普通用户。
-- 幂等性：只跑一次 —— 由执行器（tools/migrate.sh）的记录表保证；本文件不做重复保护。
-- 回滚（回到"管理台免登录"旧状态，仅限本地/内网）：
--   UPDATE user SET role = 'user' WHERE role IN ('superadmin','admin');
--   ALTER TABLE user DROP COLUMN role;

ALTER TABLE user ADD COLUMN role VARCHAR(32) NOT NULL DEFAULT 'user' AFTER avatar_url;

-- 定超管（防锁死）：库里没有任何 superadmin 时，把**最早的特权用户**（admin 里 id 最小）提升为超管；
-- 连特权用户都没有（角色列刚加、全是默认 user）就提升**最早注册的用户**。
-- ⚠️ 两条 UPDATE 都带 NOT EXISTS 守卫：第一条生效后（已有超管），第二条自动跳过；
--    子查询用派生表包裹，绕开 MySQL「不能在同一语句中更新并查询同一张表」的限制。
UPDATE user SET role = 'superadmin'
WHERE NOT EXISTS (SELECT 1 FROM (SELECT 1 FROM user WHERE role = 'superadmin') s)
  AND id = (SELECT id FROM (SELECT id FROM user WHERE role IN ('superadmin', 'admin') ORDER BY id LIMIT 1) t1);

UPDATE user SET role = 'superadmin'
WHERE NOT EXISTS (SELECT 1 FROM (SELECT 1 FROM user WHERE role = 'superadmin') s)
  AND id = (SELECT id FROM (SELECT id FROM user ORDER BY id LIMIT 1) t2);

-- 转移超管（运维手工，替换 <用户名> 后执行）：
--   UPDATE user SET role = 'admin'      WHERE role = 'superadmin' AND username <> '<用户名>';
--   UPDATE user SET role = 'superadmin' WHERE username = '<用户名>';
