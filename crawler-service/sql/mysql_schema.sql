-- 漫画聚合平台 MySQL 表结构（架构方案 §3.1，项目唯一存储方案）
-- 字符集 utf8mb4，支持中文与 emoji

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
    sync_time VARCHAR(32) NOT NULL,
    -- addtime: 首次收录时间（第一次同步写入，之后不再更新）；sync_time 为最近一次同步时间
    addtime VARCHAR(32) NOT NULL DEFAULT '',
    UNIQUE KEY uk_fingerprint (fingerprint),
    UNIQUE KEY uk_source_comic (source, source_comic_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_general_ci;

CREATE TABLE IF NOT EXISTS chapter (
    id INT AUTO_INCREMENT PRIMARY KEY,
    comic_id INT NOT NULL,
    chapter_no INT NOT NULL,
    title VARCHAR(255) NOT NULL,
    source_chapter_id VARCHAR(128) NOT NULL,
    sync_time VARCHAR(32) NOT NULL,
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
    started_at VARCHAR(32) NOT NULL,
    finished_at VARCHAR(32) NOT NULL
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_general_ci;

-- 标签字典表：每个唯一标签一行（去重），供关联表引用
CREATE TABLE IF NOT EXISTS tag (
    id INT AUTO_INCREMENT PRIMARY KEY,
    name VARCHAR(128) NOT NULL,
    UNIQUE KEY uk_tag_name (name)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_general_ci;

-- 漫画-标签 关联表：关联 tag 字典表，不再冗余存 tag 字符串
CREATE TABLE IF NOT EXISTS comic_tag (
    comic_id INT NOT NULL,
    tag_id INT NOT NULL,
    PRIMARY KEY (comic_id, tag_id),
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
    created_at VARCHAR(32) NOT NULL,
    UNIQUE KEY uk_username (username)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_general_ci;

CREATE TABLE IF NOT EXISTS favorite (
    user_id VARCHAR(64) NOT NULL,
    comic_id INT NOT NULL,
    created_at VARCHAR(32) NOT NULL,
    PRIMARY KEY (user_id, comic_id),
    KEY idx_user_created (user_id, created_at),
    CONSTRAINT fk_fav_comic FOREIGN KEY (comic_id) REFERENCES comic(id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_general_ci;

CREATE TABLE IF NOT EXISTS history (
    user_id VARCHAR(64) NOT NULL,
    comic_id INT NOT NULL,
    chapter_id INT NOT NULL,
    page_no INT NOT NULL DEFAULT 1,
    read_at VARCHAR(32) NOT NULL,
    PRIMARY KEY (user_id, comic_id),
    KEY idx_user_read (user_id, read_at),
    CONSTRAINT fk_hist_comic FOREIGN KEY (comic_id) REFERENCES comic(id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_general_ci;
