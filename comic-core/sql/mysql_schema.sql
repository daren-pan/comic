-- 漫画聚合平台 MySQL 表结构（架构方案 §3.1，项目唯一存储方案）
-- 字符集 utf8mb4，支持中文与 emoji
--
-- 【建表约定】每张表都必须有自增代理主键 `id INT AUTO_INCREMENT PRIMARY KEY`，
-- 关联表也要 —— 业务唯一性另用 UNIQUE KEY 表达（如 uk_user_comic）。
-- 理由：id 是与业务无关的稳定行标识，为后续扩展留余地（引用单行、加字段、
-- 做流水/审计、分库分表迁移）；只靠复合主键虽然当下够用，但改造成本高。
-- 时间列一律 DATETIME（勿用 VARCHAR 存时间：字符串比较的边界/排序语义都是错的）

CREATE TABLE IF NOT EXISTS comic (
    id INT AUTO_INCREMENT PRIMARY KEY,
    title VARCHAR(255) NOT NULL,
    author VARCHAR(255) NOT NULL DEFAULT '',
    cover_url VARCHAR(1024) NOT NULL DEFAULT '',
    status VARCHAR(32) NOT NULL DEFAULT '连载',
    category VARCHAR(128) NOT NULL DEFAULT '',
    description TEXT,
    fingerprint VARCHAR(64) NOT NULL,
    source VARCHAR(64) NOT NULL,
    source_comic_id VARCHAR(128) NOT NULL,
    latest_chapter_title VARCHAR(255) NOT NULL DEFAULT '',
    -- views: 累计浏览次数（详情页每次访问 +1，落库）。
    -- 热度不落库，由 (1000 + views*1 + 收藏数*2) 实时计算，见 storage/mysql/_util.py 的 HEAT_* / heat_sql()。
    views INT NOT NULL DEFAULT 0,
    -- sync_time: **内容最近变化的时刻** —— 标题/作者/状态/分类/简介/最新章节标题 任一变化，
    --            或来了新章节时刷新；**扫到但没变化不刷**（2026-10-07 改的口径）。
    --            「最近更新」列表（sort=updated）与卡片右上角角标取的就是它，
    --            所以它表示"源站这部作品最近什么时候真有变化"，而不是"我们最近什么时候扫过它"。
    --            ⚠️ 增量同步的水位**不看这一列**，那是 sync_log.finished_at。
    sync_time DATETIME NOT NULL,
    -- addtime: 首次收录时间（第一次同步写入，之后不再更新）
    addtime DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    -- 判重只看 uk_source_comic（同源精确判重）。fingerprint 是"这几行可能是同一部作品"的
    -- 观测标记（归一化标题 + 作者），**刻意不是唯一键**：不同源 / 不同译本（繁简、中日英）
    -- 各占一行、各记各自章节进度（用户 2026-09-16 决策，见 docs/architecture.md §2.3）。
    KEY idx_comic_fingerprint (fingerprint),
    UNIQUE KEY uk_source_comic (source, source_comic_id),
    -- 列表默认按最近更新倒序（sort=updated），无索引则每次列表页都 filesort；
    -- 大数据量下这是最常走的排序路径，必须有索引（见 AGENTS.md「硬性约定·性能」）。
    KEY idx_comic_sync (sync_time)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_general_ci;

CREATE TABLE IF NOT EXISTS chapter (
    id INT AUTO_INCREMENT PRIMARY KEY,
    comic_id INT NOT NULL,
    chapter_no INT NOT NULL,
    title VARCHAR(255) NOT NULL,
    source_chapter_id VARCHAR(128) NOT NULL,
    sync_time DATETIME NOT NULL,
    UNIQUE KEY uk_comic_chapter (comic_id, chapter_no),
    KEY idx_comic_id (comic_id),
    CONSTRAINT fk_chapter_comic FOREIGN KEY (comic_id) REFERENCES comic(id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_general_ci;

CREATE TABLE IF NOT EXISTS page (
    id INT AUTO_INCREMENT PRIMARY KEY,
    chapter_id INT NOT NULL,
    page_no INT NOT NULL,
    source_url VARCHAR(2048) NOT NULL,
    oss_url VARCHAR(1024) NOT NULL DEFAULT '',
    cached_status VARCHAR(16) NOT NULL DEFAULT '未转存',
    KEY idx_chapter_id (chapter_id),
    -- 转存 / 失效巡检每次都按 cached_status='未转存' 筛（page 是全库最大的表），
    -- 无索引即全表扫；带上 id 以便配合键集分页（after_id）走索引。
    KEY idx_page_cached (cached_status, id),
    CONSTRAINT fk_page_chapter FOREIGN KEY (chapter_id) REFERENCES chapter(id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_general_ci;

CREATE TABLE IF NOT EXISTS sync_log (
    id INT AUTO_INCREMENT PRIMARY KEY,
    source VARCHAR(64) NOT NULL,
    mode VARCHAR(16) NOT NULL,
    total_seen INT NOT NULL DEFAULT 0,
    new_comics INT NOT NULL DEFAULT 0,
    updated_comics INT NOT NULL DEFAULT 0,
    new_chapters INT NOT NULL DEFAULT 0,
    failed INT NOT NULL DEFAULT 0,
    started_at DATETIME NOT NULL,
    finished_at DATETIME NOT NULL
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_general_ci;

-- 标签字典表：每个唯一标签一行（去重），供关联表引用
CREATE TABLE IF NOT EXISTS tag (
    id INT AUTO_INCREMENT PRIMARY KEY,
    name VARCHAR(128) NOT NULL,
    UNIQUE KEY uk_tag_name (name)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_general_ci;

-- 漫画-标签 关联表：关联 tag 字典表，不再冗余存 tag 字符串
CREATE TABLE IF NOT EXISTS comic_tag (
    -- id: 代理主键。关系的唯一性由 uk_comic_tag 保证；保留自增 id 是为后续扩展
    -- （引用某条关联、给关联加字段、做流水/审计）留出稳定的行标识。
    id INT AUTO_INCREMENT PRIMARY KEY,
    comic_id INT NOT NULL,
    tag_id INT NOT NULL,
    UNIQUE KEY uk_comic_tag (comic_id, tag_id),
    KEY idx_comic_tag_tag (tag_id),
    CONSTRAINT fk_tag_comic FOREIGN KEY (comic_id) REFERENCES comic(id),
    CONSTRAINT fk_tag_tag FOREIGN KEY (tag_id) REFERENCES tag(id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_general_ci;

-- 用户中心（架构方案 §3.1 user/favorite/history）
CREATE TABLE IF NOT EXISTS user (
    id INT AUTO_INCREMENT PRIMARY KEY,
    username VARCHAR(64) NOT NULL,
    password_hash VARCHAR(255) NOT NULL,
    nickname VARCHAR(64) NOT NULL DEFAULT '',
    avatar_url VARCHAR(512) NOT NULL DEFAULT '',
    -- 角色三档：'superadmin' = 超级管理员（管理台/日志/授权页，**全库唯一**，只由"首个注册用户"产生）；
    --          'admin'      = 普通管理员（管理台/日志，**进不了授权页**）；
    --          'user'       = 普通用户（默认，无管理台权限）。
    -- 引导与迁移见 api-service/routers/auth.py 与 tools/add_user_role.py。
    role VARCHAR(32) NOT NULL DEFAULT 'user',
    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE KEY uk_username (username)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_general_ci;

CREATE TABLE IF NOT EXISTS favorite (
    id INT AUTO_INCREMENT PRIMARY KEY,
    user_id VARCHAR(64) NOT NULL,
    comic_id INT NOT NULL,
    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    -- 唯一性：一个用户对一部漫画只能有一条收藏（PUT 幂等依赖它）
    UNIQUE KEY uk_user_comic (user_id, comic_id),
    KEY idx_user_created (user_id, created_at),
    CONSTRAINT fk_fav_comic FOREIGN KEY (comic_id) REFERENCES comic(id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_general_ci;

CREATE TABLE IF NOT EXISTS history (
    id INT AUTO_INCREMENT PRIMARY KEY,
    user_id VARCHAR(64) NOT NULL,
    comic_id INT NOT NULL,
    chapter_id INT NOT NULL,
    page_no INT NOT NULL DEFAULT 1,
    read_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    -- 唯一性：一个用户对一部漫画只保留一条**最新进度**（upsert 依赖它）
    UNIQUE KEY uk_user_comic (user_id, comic_id),
    KEY idx_user_read (user_id, read_at),
    CONSTRAINT fk_hist_comic FOREIGN KEY (comic_id) REFERENCES comic(id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_general_ci;

-- ---------------------------------------------------------------------------
-- 运行日志（逐条落库）。与 sync_log 的分工：sync_log 是**任务级统计**（每源每次跑一行汇总），
-- 本表是**逐条日志**，给管理台「日志查询」页按条件筛（级别/源站/作品/章节/任务/时间/关键字）。
-- 写入方：`comic_crawler.storage.mysql.log_handler`（后台线程 + 批量 executemany，
-- 不是每条一次连接 —— 见 AGENTS.md「硬性约定·性能」）；读取方：api-service 的 services/logs.py。
-- 前 5 个「通用字段」所有日志都有；其后是业务字段，由调用方通过
-- `extra={"log_fields": {...}}` 提供（拿不到就留空，不影响入库）。
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS log_record (
    id INT AUTO_INCREMENT PRIMARY KEY,
    -- 时间用 DATETIME（项目约定时间列一律 DATETIME）；同秒多条靠 id 兜底排序
    -- 语义：**写入进程的本机时间**（容器必须配 TZ=Asia/Shanghai）。日志页出参一律
    -- 按北京时间（services/logs.to_beijing 会按进程时区补差），所以这里不做 UTC 转换。
    created_at DATETIME NOT NULL,
    level VARCHAR(8) NOT NULL DEFAULT '',
    logger VARCHAR(64) NOT NULL DEFAULT '',
    message TEXT,
    task_id VARCHAR(64) NOT NULL DEFAULT '',
    task_type VARCHAR(16) NOT NULL DEFAULT '',
    exc_type VARCHAR(64) NOT NULL DEFAULT '',
    exc_text TEXT,
    source VARCHAR(64) NOT NULL DEFAULT '',
    comic_id INT NULL,
    comic_title VARCHAR(255) NOT NULL DEFAULT '',
    chapter_id INT NULL,
    chapter_title VARCHAR(255) NOT NULL DEFAULT '',
    endpoint VARCHAR(255) NOT NULL DEFAULT '',
    pages INT NULL,
    reason VARCHAR(255) NOT NULL DEFAULT '',
    event VARCHAR(32) NOT NULL DEFAULT '',
    KEY idx_log_created (created_at),
    KEY idx_log_level_created (level, created_at),
    KEY idx_log_source_created (source, created_at),
    KEY idx_log_task (task_id),
    KEY idx_log_comic (comic_id, created_at)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_general_ci;

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
    id INT AUTO_INCREMENT PRIMARY KEY,
    task_id VARCHAR(64) NOT NULL,
    task_type VARCHAR(16) NOT NULL DEFAULT '',
    status VARCHAR(16) NOT NULL DEFAULT 'running',
    message VARCHAR(500) NOT NULL DEFAULT '',
    result JSON NULL,
    params JSON NULL,
    -- 触发账号：user 表被删/改名后也还能看懂是谁点的，所以 username 冗余存一份
    user_id INT NULL,
    username VARCHAR(64) NOT NULL DEFAULT '',
    started_at DATETIME NOT NULL,
    finished_at DATETIME NULL,
    UNIQUE KEY uk_task_id (task_id),
    KEY idx_task_started (started_at),
    KEY idx_task_user_started (user_id, started_at),
    KEY idx_task_status (status)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_general_ci;

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
    id INT AUTO_INCREMENT PRIMARY KEY,
    -- 任务消息 = 任务类型（sync/inspect/heal/import/schedule）；其余写者自定义（system/notice…）
    kind VARCHAR(16) NOT NULL DEFAULT '',
    -- info / warn / error —— 前端据此显示 完成 / 警告 / 失败（**同时承载任务成败**，不另设 status 列）
    level VARCHAR(8) NOT NULL DEFAULT 'info',
    title VARCHAR(255) NOT NULL DEFAULT '',
    body TEXT,
    -- **入参快照**（触发时的关键参数：`since`/`until`/`mode`/`limit`/`sources`/`action`/`keyword`…）。
    -- 用途：一眼看出"这条消息说的是哪段时间范围内的数据"（`since` 就是起始时间；为空 = 按源自身水位），
    -- 以及复现"当时点的是什么"。与 `admin_task.params` 同源，但**消息自带一份** ——
    -- 消息是独立记录（别的模块也能写），不该反过来依赖任务表还在不在。
    params JSON NULL,
    task_id VARCHAR(64) NOT NULL DEFAULT '',
    source VARCHAR(64) NOT NULL DEFAULT '',
    -- **触发人**（谁干的）：系统/定时轮次为空；username 冗余一份，账号改名删号后仍看得懂
    user_id INT NULL,
    username VARCHAR(64) NOT NULL DEFAULT '',
    -- **收件范围**（两个条件同时成立才可见）：
    --   to_user_id：定向发给某个人（NULL = 不限人）
    --   min_role  ：最低角色要求（'' = 所有登录用户；'user' < 'admin' < 'superadmin'，
    --               即 min_role='admin' 时**超管也能看到** —— 超管是管理员的超集）
    to_user_id INT NULL,
    min_role VARCHAR(16) NOT NULL DEFAULT '',
    created_at DATETIME NOT NULL,
    KEY idx_msg_created (created_at),
    KEY idx_msg_kind_created (kind, created_at),
    KEY idx_msg_task (task_id),
    KEY idx_msg_to_user (to_user_id, created_at),
    KEY idx_msg_role_created (min_role, created_at)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_general_ci;

-- ---------------------------------------------------------------------------
-- 消息的**已读记账**：一行 = "某账号读过某条消息"。
-- 为什么不把 read_at 放在 message 上：消息是**广播**的（一条给所有人看），已读必须按人算 ——
-- 否则 A 点开消息页就把 B 的未读角标也清了。
-- 未读数 = 可见消息数 − 本人在本表里的行数（见 `message_store.unread_count`）。
-- ⚠️ 没有 FOREIGN KEY：与本项目其它表一致（关联关系由代码保证，避免删除顺序耦合）。
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS message_read (
    id INT AUTO_INCREMENT PRIMARY KEY,
    message_id INT NOT NULL,
    user_id INT NOT NULL,
    read_at DATETIME NOT NULL,
    UNIQUE KEY uk_msg_read (message_id, user_id),
    KEY idx_msg_read_user (user_id, read_at)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_general_ci;
