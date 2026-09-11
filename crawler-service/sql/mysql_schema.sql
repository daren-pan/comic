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
    -- 热度不落库，由 (1000 + views*1 + 收藏数*2) 实时计算，见 mysql_storage.HEAT_* / heat_sql()。
    views INT NOT NULL DEFAULT 0,
    sync_time DATETIME NOT NULL,
    -- addtime: 首次收录时间（第一次同步写入，之后不再更新）；sync_time 为最近一次同步时间
    addtime DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE KEY uk_fingerprint (fingerprint),
    UNIQUE KEY uk_source_comic (source, source_comic_id)
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
