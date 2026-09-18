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
    sync_time DATETIME NOT NULL,
    -- addtime: 首次收录时间（第一次同步写入，之后不再更新）；sync_time 为最近一次同步时间
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
