-- 漫画聚合平台 MySQL 表结构（架构方案 §3.1，项目唯一存储方案）
-- 字符集 utf8mb4，支持中文与 emoji
-- 表与字段一律带 COMMENT（Navicat 等客户端直接可见用途说明；本文件是注释唯一真源，
-- 已有库用 tools/add_table_comments.py 刷入）
--
-- 【建表约定】每张表都必须有自增代理主键 `id INT AUTO_INCREMENT PRIMARY KEY`，
-- 关联表也要 —— 业务唯一性另用 UNIQUE KEY 表达（如 uk_user_comic）。
-- 理由：id 是与业务无关的稳定行标识，为后续扩展留余地（引用单行、加字段、
-- 做流水/审计、分库分表迁移）；只靠复合主键虽然当下够用，但改造成本高。
-- 时间列一律 DATETIME（勿用 VARCHAR 存时间：字符串比较的边界/排序语义都是错的）

CREATE TABLE IF NOT EXISTS comic (
    id INT AUTO_INCREMENT PRIMARY KEY COMMENT '自增主键',
    title VARCHAR(255) NOT NULL COMMENT '标题',
    author VARCHAR(255) NOT NULL DEFAULT '' COMMENT '作者',
    cover_url VARCHAR(1024) NOT NULL DEFAULT '' COMMENT '封面图 URL（源站外链）',
    status VARCHAR(32) NOT NULL DEFAULT '连载' COMMENT '连载状态（连载 / 完结…）',
    category VARCHAR(128) NOT NULL DEFAULT '' COMMENT '原始分类串（展示用；标签关联见 comic_tag）',
    description TEXT COMMENT '简介',
    fingerprint VARCHAR(64) NOT NULL COMMENT '判重观测标记（归一化标题+作者；非唯一键，跨源不合并）',
    source VARCHAR(64) NOT NULL COMMENT '收录源（zaimanhua / copymanga…）',
    source_comic_id VARCHAR(128) NOT NULL COMMENT '源站作品 id（与 source 组成同源唯一键）',
    latest_chapter_title VARCHAR(255) NOT NULL DEFAULT '' COMMENT '最新章节标题',
    -- views: 累计浏览次数（详情页每次访问 +1，落库）。
    -- 热度不落库，由 (1000 + views*1 + 收藏数*2) 实时计算，见 storage/mysql/_util.py 的 HEAT_* / heat_sql()。
    views INT NOT NULL DEFAULT 0 COMMENT '累计浏览次数（热度=1000+views+2×收藏数）',
    -- sync_time: **内容最近变化的时刻** —— 标题/作者/状态/分类/简介/最新章节标题 任一变化，
    --            或来了新章节时刷新；**扫到但没变化不刷**（2026-10-07 改的口径）。
    --            「最近更新」列表（sort=updated）与卡片右上角角标取的就是它，
    --            所以它表示"源站这部作品最近什么时候真有变化"，而不是"我们最近什么时候扫过它"。
    --            ⚠️ 增量同步的水位**不看这一列**，那是 sync_log.finished_at。
    sync_time DATETIME NOT NULL COMMENT '内容最近变化时刻（列表排序/角标用；增量水位看 sync_log.finished_at）',
    -- addtime: 首次收录时间（第一次同步写入，之后不再更新）
    addtime DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP COMMENT '首次收录时间（之后不再更新）',
    -- listed: 1 = 上架（前台可见），0 = **下架**。
    --   下架后列表 / 搜索 / 收藏 / 历史都不再出现，**详情页直接 404**（用户 2026-10-09 决策：
    --   「无法搜索到该作品并进入详情页」）。下架只改这一列、**不删数据**，重新上架即恢复；
    --   采集侧**照旧更新**（与上架状态无关，见 crawler-service/README.md）。
    listed TINYINT NOT NULL DEFAULT 1 COMMENT '上下架：1=上架可见，0=下架（前台不可见、详情 404，数据保留）',
    -- comment_enabled: 该作品是否开放评论（1/0）。
    --   ⚠️ 这是**单作品**开关；**全站总开关**存在 `app_setting` 表的 `comment_enabled` 键上，
    --   有效值 = 总开关 AND 本列（见 `storage/mysql/comment_store.effective_enabled`）。
    comment_enabled TINYINT NOT NULL DEFAULT 1 COMMENT '本作品评论开关（有效值 = 全站总开关 AND 本列）',
    -- 判重只看 uk_source_comic（同源精确判重）。fingerprint 是"这几行可能是同一部作品"的
    -- 观测标记（归一化标题 + 作者），**刻意不是唯一键**：不同源 / 不同译本（繁简、中日英）
    -- 各占一行、各记各自章节进度（用户 2026-09-16 决策，见 docs/architecture.md §2.3）。
    KEY idx_comic_fingerprint (fingerprint),
    UNIQUE KEY uk_source_comic (source, source_comic_id),
    -- 列表默认按最近更新倒序（sort=updated），无索引则每次列表页都 filesort；
    -- 大数据量下这是最常走的排序路径，必须有索引（见 AGENTS.md「硬性约定·性能」）。
    KEY idx_comic_sync (sync_time),
    -- 前台列表一律带 `WHERE c.listed = 1`（下架过滤），排序仍是 sync_time DESC ——
    -- 复合索引让「过滤 + 排序」走同一条索引；单列 `listed` 选择性太低（绝大多数行都是 1），
    -- MySQL 多半不会用它。
    KEY idx_comic_listed_sync (listed, sync_time)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_general_ci COMMENT='作品主表：一行 = 一个收录源收录的一部作品（同源判重、跨源不合并）';

CREATE TABLE IF NOT EXISTS chapter (
    id INT AUTO_INCREMENT PRIMARY KEY COMMENT '自增主键',
    comic_id INT NOT NULL COMMENT '所属作品 id（comic.id）',
    chapter_no INT NOT NULL COMMENT '话号（章节排序用）',
    title VARCHAR(255) NOT NULL COMMENT '章节标题',
    source_chapter_id VARCHAR(128) NOT NULL COMMENT '源站章节 id',
    sync_time DATETIME NOT NULL COMMENT '本章内容最近同步/变化的时刻',
    UNIQUE KEY uk_comic_chapter (comic_id, chapter_no),
    KEY idx_comic_id (comic_id),
    CONSTRAINT fk_chapter_comic FOREIGN KEY (comic_id) REFERENCES comic(id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_general_ci COMMENT='章节表：一行 = 作品下的一话（同作品内 chapter_no 唯一）';

CREATE TABLE IF NOT EXISTS page (
    id INT AUTO_INCREMENT PRIMARY KEY COMMENT '自增主键',
    chapter_id INT NOT NULL COMMENT '所属章节 id（chapter.id）',
    page_no INT NOT NULL COMMENT '页号（1 起，章节内有序）',
    source_url VARCHAR(2048) NOT NULL COMMENT '源站图片 URL',
    oss_url VARCHAR(1024) NOT NULL DEFAULT '' COMMENT '转存后的图库 key（空 = 未转存）',
    cached_status VARCHAR(16) NOT NULL DEFAULT '未转存' COMMENT '转存状态（未转存 / 已转存 / 失效…）',
    KEY idx_chapter_id (chapter_id),
    -- 转存 / 失效巡检每次都按 cached_status='未转存' 筛（page 是全库最大的表），
    -- 无索引即全表扫；带上 id 以便配合键集分页（after_id）走索引。
    KEY idx_page_cached (cached_status, id),
    CONSTRAINT fk_page_chapter FOREIGN KEY (chapter_id) REFERENCES chapter(id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_general_ci COMMENT='页面表：一行 = 章节下的一页图片（全库最大的表；转存/巡检按 cached_status 筛）';

CREATE TABLE IF NOT EXISTS sync_log (
    id INT AUTO_INCREMENT PRIMARY KEY COMMENT '自增主键',
    source VARCHAR(64) NOT NULL COMMENT '数据源名',
    mode VARCHAR(16) NOT NULL COMMENT '采集模式（full 全量 / incremental 增量…）',
    total_seen INT NOT NULL DEFAULT 0 COMMENT '本次扫到的作品数',
    new_comics INT NOT NULL DEFAULT 0 COMMENT '新增作品数',
    updated_comics INT NOT NULL DEFAULT 0 COMMENT '更新作品数',
    new_chapters INT NOT NULL DEFAULT 0 COMMENT '新增章节数',
    failed INT NOT NULL DEFAULT 0 COMMENT '失败数',
    started_at DATETIME NOT NULL COMMENT '开始时间',
    finished_at DATETIME NOT NULL COMMENT '结束时间（增量同步水位）'
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_general_ci COMMENT='采集任务统计：每源每次跑一行汇总（逐条明细看 log_record）';

-- 标签字典表：每个唯一标签一行（去重），供关联表引用
CREATE TABLE IF NOT EXISTS tag (
    id INT AUTO_INCREMENT PRIMARY KEY COMMENT '自增主键',
    name VARCHAR(128) NOT NULL COMMENT '标签名（唯一）',
    UNIQUE KEY uk_tag_name (name)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_general_ci COMMENT='标签字典表：每个唯一标签一行（去重）';

-- 漫画-标签 关联表：关联 tag 字典表，不再冗余存 tag 字符串
CREATE TABLE IF NOT EXISTS comic_tag (
    -- id: 代理主键。关系的唯一性由 uk_comic_tag 保证；保留自增 id 是为后续扩展
    -- （引用某条关联、给关联加字段、做流水/审计）留出稳定的行标识。
    id INT AUTO_INCREMENT PRIMARY KEY COMMENT '自增主键（代理键，关系唯一性由 uk_comic_tag 保证）',
    comic_id INT NOT NULL COMMENT '作品 id（comic.id）',
    tag_id INT NOT NULL COMMENT '标签 id（tag.id）',
    UNIQUE KEY uk_comic_tag (comic_id, tag_id),
    KEY idx_comic_tag_tag (tag_id),
    CONSTRAINT fk_tag_comic FOREIGN KEY (comic_id) REFERENCES comic(id),
    CONSTRAINT fk_tag_tag FOREIGN KEY (tag_id) REFERENCES tag(id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_general_ci COMMENT='漫画-标签关联表：一行 = 作品挂某个标签';

-- 用户中心（架构方案 §3.1 user/favorite/history）
CREATE TABLE IF NOT EXISTS user (
    id INT AUTO_INCREMENT PRIMARY KEY COMMENT '自增主键',
    username VARCHAR(64) NOT NULL COMMENT '登录名（唯一）',
    password_hash VARCHAR(255) NOT NULL COMMENT '密码哈希（不可逆）',
    nickname VARCHAR(64) NOT NULL DEFAULT '' COMMENT '昵称',
    avatar_url VARCHAR(512) NOT NULL DEFAULT '' COMMENT '头像 URL',
    -- 角色三档：'superadmin' = 超级管理员（管理台/日志/授权页，**全库唯一**，只由"首个注册用户"产生）；
    --          'admin'      = 普通管理员（管理台/日志，**进不了授权页**）；
    --          'user'       = 普通用户（默认，无管理台权限）。
    -- 引导与迁移见 api-service/routers/auth.py 与 tools/add_user_role.py。
    role VARCHAR(32) NOT NULL DEFAULT 'user' COMMENT '角色：superadmin 超管（全库唯一）/ admin 管理员 / user 普通用户',
    -- 绑定邮箱（2026-10-24 新增，「忘记密码」靠它收验证码）。
    -- ⚠️ **必须可 NULL**：MySQL 唯一索引不比较 NULL（任意多行未绑定都合法），而 '' 是普通值 ——
    --    第二行 '' 直接撞 uk_email 报 1062，上线即挡死所有未绑定用户。代码里空串显式转 NULL。
    email VARCHAR(128) NULL DEFAULT NULL COMMENT '绑定邮箱（找回密码用；NULL = 未绑定，同一邮箱全库唯一）',
    -- 密码最近修改时刻：改密 / 重置时刷新，`get_current_user` 据此让**更早签发的 token 失效**。
    -- 不加索引：只在拿到整行后做一次内存比较，没有按它查询的路径。
    password_changed_at DATETIME NULL DEFAULT NULL COMMENT '密码最近修改时刻（改密 / 重置时刷新；旧 token 据此失效，NULL = 从未改过）',
    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP COMMENT '注册时间',
    UNIQUE KEY uk_username (username),
    -- 邮箱全库唯一：既是「找回密码」的定位方式，也兜住并发绑定同一邮箱（两账号抢写 → 1062 → 409）。
    -- 排序规则 utf8mb4_general_ci 下 A@x.com / a@x.com 视为重复；代码仍统一 strip().lower() 后写入。
    UNIQUE KEY uk_email (email)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_general_ci COMMENT='用户表（角色三档 + 可绑定邮箱用于找回密码）';

CREATE TABLE IF NOT EXISTS favorite (
    id INT AUTO_INCREMENT PRIMARY KEY COMMENT '自增主键',
    user_id VARCHAR(64) NOT NULL COMMENT '用户标识（登录账号 id；兼容匿名 UUID）',
    comic_id INT NOT NULL COMMENT '作品 id（comic.id）',
    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP COMMENT '收藏时间',
    -- 唯一性：一个用户对一部漫画只能有一条收藏（PUT 幂等依赖它）
    UNIQUE KEY uk_user_comic (user_id, comic_id),
    KEY idx_user_created (user_id, created_at),
    CONSTRAINT fk_fav_comic FOREIGN KEY (comic_id) REFERENCES comic(id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_general_ci COMMENT='收藏表：一行 = 某用户收藏某作品（一人一作品一条）';

CREATE TABLE IF NOT EXISTS history (
    id INT AUTO_INCREMENT PRIMARY KEY COMMENT '自增主键',
    user_id VARCHAR(64) NOT NULL COMMENT '用户标识（登录账号 id；兼容匿名 UUID）',
    comic_id INT NOT NULL COMMENT '作品 id（comic.id）',
    chapter_id INT NOT NULL COMMENT '最近读到的章节 id',
    page_no INT NOT NULL DEFAULT 1 COMMENT '最近读到的页号',
    read_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP COMMENT '最近阅读时间',
    -- 唯一性：一个用户对一部漫画只保留一条**最新进度**（upsert 依赖它）
    UNIQUE KEY uk_user_comic (user_id, comic_id),
    KEY idx_user_read (user_id, read_at),
    CONSTRAINT fk_hist_comic FOREIGN KEY (comic_id) REFERENCES comic(id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_general_ci COMMENT='阅读历史：一行 = 某用户对某作品的最新阅读进度（一人一作品一条）';

-- ---------------------------------------------------------------------------
-- 运行日志（逐条落库）。与 sync_log 的分工：sync_log 是**任务级统计**（每源每次跑一行汇总），
-- 本表是**逐条日志**，给管理台「日志查询」页按条件筛（级别/源站/作品/章节/任务/时间/关键字）。
-- 写入方：`comic_crawler.storage.mysql.log_handler`（后台线程 + 批量 executemany，
-- 不是每条一次连接 —— 见 AGENTS.md「硬性约定·性能」）；读取方：api-service 的 services/logs.py。
-- 前 5 个「通用字段」所有日志都有；其后是业务字段，由调用方通过
-- `extra={"log_fields": {...}}` 提供（拿不到就留空，不影响入库）。
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS log_record (
    id INT AUTO_INCREMENT PRIMARY KEY COMMENT '自增主键',
    -- 时间用 DATETIME（项目约定时间列一律 DATETIME）；同秒多条靠 id 兜底排序
    -- 语义：**写入进程的本机时间**（容器必须配 TZ=Asia/Shanghai）。日志页出参一律
    -- 按北京时间（services/logs.to_beijing 会按进程时区补差），所以这里不做 UTC 转换。
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

-- ---------------------------------------------------------------------------
-- 管理台「后台任务」表：一次**手动触发**（采集 / 巡检 / 封面自愈 / 按需导入）= 一行。
-- 写入方：api-service 的 `services/tasks.py`（触发时插 running，结束时改 done/failed）；
-- 读取方：同文件的 `recent()` / `get()` → 管理台任务列表与前端 `taskId` 轮询。
-- ⚠️ 这张表以前是**进程内 dict**（api 一重启任务就没了、也答不出"是谁点的"）。落库之后：
--    ① 重启不丢 —— 残留的 running 由 `tasks.reap_stale()` 标成"服务重启，任务中断"；
--    ② 与**触发账号**绑定（user_id + username 冗余一份），可追溯。
-- `result` / `params` 用 JSON：前者是给前端的原始 payload，后者是入参快照（复盘用）。
-- ⚠️ 采集的**业务明细**不在本表：每源统计看 `sync_log`，逐条日志看 `log_record`（按 task_id 关联）。
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS admin_task (
    id INT AUTO_INCREMENT PRIMARY KEY COMMENT '自增主键',
    task_id VARCHAR(64) NOT NULL COMMENT '任务号（唯一，形如 sync-1-aaa；log_record 按它关联）',
    task_type VARCHAR(16) NOT NULL DEFAULT '' COMMENT '任务类型（sync / transfer / inspect / import / heal / schedule）',
    status VARCHAR(16) NOT NULL DEFAULT 'running' COMMENT '状态：running / done / failed',
    message VARCHAR(500) NOT NULL DEFAULT '' COMMENT '状态说明（一句话）',
    result JSON NULL COMMENT '结果 payload（JSON，给前端展示）',
    params JSON NULL COMMENT '入参快照（JSON，复盘「当时点的是什么」）',
    -- 触发账号：user 表被删/改名后也还能看懂是谁点的，所以 username 冗余存一份
    user_id INT NULL COMMENT '触发账号 id（NULL = 系统/定时）',
    username VARCHAR(64) NOT NULL DEFAULT '' COMMENT '触发账号名（冗余，账号删改后仍可读）',
    started_at DATETIME NOT NULL COMMENT '开始时间',
    finished_at DATETIME NULL COMMENT '结束时间',
    UNIQUE KEY uk_task_id (task_id),
    KEY idx_task_started (started_at),
    KEY idx_task_user_started (user_id, started_at),
    KEY idx_task_status (status)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_general_ci COMMENT='管理台后台任务：一次手动触发或定时轮次 = 一行（状态/归属/入参快照，重启不丢）';

-- ---------------------------------------------------------------------------
-- 消息中心（`message` 表）：**平台级的消息流** —— 顶栏铃铛、消息页读的就是它。
-- 面向**所有登录用户**（2026-10-06 从"仅管理员"改成按角色/指定用户可见），
-- 所以每条消息都带**收件范围**（见下面 `to_user_id` / `min_role` 两列）。
-- 写入方**只走 HTTP `POST /api/messages`**（见 api-service/routers/messages.py）：
--   · api 自己：任务收尾时发一条（services/tasks.py，进程内直调；收件范围 = 管理员及以上）；
--   · 独立进程 `comic-scheduler`：一轮跑完发一条（**服务令牌**鉴权，见 comic_core/notify.py）；
--   · 将来的外部系统 / 运维脚本（同一个接口，可指定 `toUserId` / `minRole`）。
-- 读取方：api 的 services/messages.py —— 列表 + 未读数 + 标记已读（**都按当前账号过滤/记账**）。
-- ⚠️ 为什么不直接读 `admin_task`：任务只是消息的**来源之一** —— 消息中心要能被别的模块写入
--    （运维通知、源站异常、将来的"你收藏的作品更新了"…），所以独立成表。而"**正在跑**的任务"
--    还没有消息，由读取接口在返回时**临时并进来**（见 `services/messages.feed`）—— 跑完再由任务侧
--    发那条消息。这样同一件事**不会**在任务表与消息表里各存一份状态（两份迟早不一致）。
-- ⚠️ **已读按账号各一份**（`message_read` 关联表）：同一条广播消息，A 读过不该让 B 的角标消失。
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS message (
    id INT AUTO_INCREMENT PRIMARY KEY COMMENT '自增主键',
    -- 任务消息 = 任务类型（sync/inspect/heal/import/schedule）；其余写者自定义（system/notice…）
    kind VARCHAR(16) NOT NULL DEFAULT '' COMMENT '消息类型（任务消息=任务类型；其余写者自定义）',
    -- info / warn / error —— 前端据此显示 完成 / 警告 / 失败（**同时承载任务成败**，不另设 status 列）
    level VARCHAR(8) NOT NULL DEFAULT 'info' COMMENT '级别：info / warn / error（同时承载任务成败）',
    title VARCHAR(255) NOT NULL DEFAULT '' COMMENT '标题',
    body TEXT COMMENT '正文',
    -- **入参快照**（触发时的关键参数：`since`/`until`/`mode`/`limit`/`sources`/`action`/`keyword`…）。
    -- 用途：一眼看出"这条消息说的是哪段时间范围内的数据"（`since` 就是起始时间；为空 = 按源自身水位），
    -- 以及复现"当时点的是什么"。与 `admin_task.params` 同源，但**消息自带一份** ——
    -- 消息是独立记录（别的模块也能写），不该反过来依赖任务表还在不在。
    params JSON NULL COMMENT '入参快照（JSON，消息自带一份，不依赖任务表）',
    task_id VARCHAR(64) NOT NULL DEFAULT '' COMMENT '关联任务号（admin_task.task_id）',
    source VARCHAR(64) NOT NULL DEFAULT '' COMMENT '数据源（任务类消息）',
    -- **触发人**（谁干的）：系统/定时轮次为空；username 冗余一份，账号改名删号后仍看得懂
    user_id INT NULL COMMENT '触发人 id（系统/定时为空）',
    username VARCHAR(64) NOT NULL DEFAULT '' COMMENT '触发人名（冗余）',
    -- **收件范围**（两个条件同时成立才可见）：
    --   to_user_id：定向发给某个人（NULL = 不限人）
    --   min_role  ：最低角色要求（'' = 所有登录用户；'user' < 'admin' < 'superadmin'，
    --               即 min_role='admin' 时**超管也能看到** —— 超管是管理员的超集）
    to_user_id INT NULL COMMENT '定向收件人 id（NULL = 不限人）',
    min_role VARCHAR(16) NOT NULL DEFAULT '' COMMENT '最低可见角色（空 = 所有登录用户，admin = 管理员及以上）',
    created_at DATETIME NOT NULL COMMENT '创建时间',
    KEY idx_msg_created (created_at),
    KEY idx_msg_kind_created (kind, created_at),
    KEY idx_msg_task (task_id),
    KEY idx_msg_to_user (to_user_id, created_at),
    KEY idx_msg_role_created (min_role, created_at)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_general_ci COMMENT='消息中心：平台级消息流（顶栏铃铛 / 消息页数据源）';

-- ---------------------------------------------------------------------------
-- 消息的**已读记账**：一行 = "某账号读过某条消息"。
-- 为什么不把 read_at 放在 message 上：消息是**广播**的（一条给所有人看），已读必须按人算 ——
-- 否则 A 点开消息页就把 B 的未读角标也清了。
-- 未读数 = 可见消息数 − 本人在本表里的行数（见 `message_store.unread_count`）。
-- ⚠️ 没有 FOREIGN KEY：与本项目其它表一致（关联关系由代码保证，避免删除顺序耦合）。
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS message_read (
    id INT AUTO_INCREMENT PRIMARY KEY COMMENT '自增主键',
    message_id INT NOT NULL COMMENT '消息 id（message.id）',
    user_id INT NOT NULL COMMENT '账号 id',
    read_at DATETIME NOT NULL COMMENT '读取时间',
    UNIQUE KEY uk_msg_read (message_id, user_id),
    KEY idx_msg_read_user (user_id, read_at)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_general_ci COMMENT='消息已读记账：一行 = 某账号读过某条消息（按账号各一份）';

-- ---------------------------------------------------------------------------
-- 评论（2026-10-09 新增）：漫画详情页底部的评论区。
-- **只允许登录用户发表**（用户决策）—— 所以 `user_id` 一定是账号 id（不是匿名 UUID）。 
-- 作者昵称**不冗余**：读取时 JOIN `user` 取**当前**昵称（改名后评论区跟着变），
-- 账号已删则显示「已注销用户」（LEFT JOIN 得到 NULL，由读取侧兜底）。
-- ⚠️ 与前几轮的口径一致：**没有外键到 `user`**（与 favorite / history / message_read 一样，
--    关联关系由代码保证，避免删除顺序耦合）；但**保留**到 `comic` 的外键
--    （与 chapter/page/favorite/history 一致 —— 作品行是真源，不该出现指向空气的评论）。
-- 权限与开关：发表要 **登录** + **评论区开启**（有效值 = 全站总开关 AND `comic.comment_enabled`，
--    见 storage/mysql/comment_store.effective_enabled）；删除要 `require_admin`。
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS comment (
    id INT AUTO_INCREMENT PRIMARY KEY COMMENT '自增主键',
    comic_id INT NOT NULL COMMENT '作品 id（comic.id）',
    -- 作者账号 id（**字符串列**，与 favorite / history 的 user_id 同型：
    -- 那边把匿名 UUID 也塞在同一列里；评论只收登录用户，但保持列型一致便于共用 helper）
    user_id VARCHAR(64) NOT NULL COMMENT '作者账号 id（字符串列，与 favorite/history 同型）',
    content VARCHAR(500) NOT NULL COMMENT '评论内容（≤500 字）',
    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP COMMENT '发表时间',
    -- 列表：某作品的最新在前 —— (comic_id, id DESC) 一条索引既过滤又排序
    KEY idx_comment_comic (comic_id, id),
    -- 按人查（"这个人发了什么" / 将来的频控）
    KEY idx_comment_user (user_id, created_at),
    CONSTRAINT fk_comment_comic FOREIGN KEY (comic_id) REFERENCES comic(id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_general_ci COMMENT='评论表：漫画详情页评论区（只允许登录用户发表）';

-- ---------------------------------------------------------------------------
-- 全站级键值配置（2026-10-09 新增）：目前只放 `comment_enabled`（全站评论总开关）。
-- 为什么建表而不是塞 `.env`：这是**运行期要能改**的业务开关（管理台一个按钮），
-- 环境变量改完要重启容器，不合适。也不做成 `comic` 上的列 —— 它是"全站"级、不是"某一行"的。
-- 值一律按字符串存（'1' / '0' / 'true'…），由读取方解释；键不存在 = 取调用方给的默认值。
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS app_setting (
    k VARCHAR(64) NOT NULL PRIMARY KEY COMMENT '配置键（主键）',
    v VARCHAR(255) NOT NULL DEFAULT '' COMMENT '配置值（字符串，由读取方解释）',
    updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP COMMENT '更新时间'
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_general_ci COMMENT='全站级键值配置（目前放 comment_enabled 全站评论总开关）';

-- ---------------------------------------------------------------------------
-- 邮箱验证码（2026-10-24 新增，配合 user.email 做「忘记密码」与「绑定邮箱」）。
-- 一行 = 一次发码请求；**无论邮箱是否已注册都落行** —— 让 60s 冷却与小时配额对
-- 「已注册」「未注册」完全一致，否则状态码/次数差异就成了邮箱枚举侧信道。
--
-- 为什么不塞进 user 表：一行存一个码 → 新码只能覆盖旧码，无法审计、无法按 IP 限流；
-- 而且 user 是鉴权热表（`get_current_user` 每个带 token 的请求都 SELECT *），
-- 临时数据不该蹭进来。为什么不用 Redis：本项目唯一存储就是 MySQL（无缓存组件）。
--
-- 码**只存 HMAC-SHA256**（密钥复用 COMIC_JWT_SECRET）：库泄露也无法离线爆破 6 位空间。
-- 无外键：账号改绑 / 删号后这些行仍需按发码记录限流，外键会阻止历史行保留。
-- ---------------------------------------------------------------------------
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
