"""漫画聚合平台 HTTP API 服务（架构方案 §4：网关 + 微服务）。

- 复用采集服务（crawler-service）的 Storage 抽象读取 SQLite 库，同一套存储接口；
- 统一响应格式 { code, message, data }（架构方案约定）；
- 同时托管前端构建产物（comic-web/dist），同源部署，免 CORS/代理；
- 图片端点：优先返回已转存的真实文件（OSS），缺失/占位时回退生成 SVG 占位图。

运行：
    PYTHONPATH 无需设置（本文件自动把 crawler-service/src 加入 sys.path）
    uvicorn main:app --host 127.0.0.1 --port 8000
"""
from __future__ import annotations

import os
import sqlite3
import sys
from contextlib import contextmanager
from datetime import datetime, timedelta
from pathlib import Path

import uvicorn
import bcrypt
import jwt
from fastapi import FastAPI, HTTPException, Depends
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import Response
from fastapi.staticfiles import StaticFiles
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from pydantic import BaseModel

APP_DIR = Path(__file__).resolve().parent

# 发布模式：comic_crawler 包与 main.py 同目录；开发模式：复用 crawler-service/src
if (APP_DIR / "comic_crawler").is_dir():
    sys.path.insert(0, str(APP_DIR))
CRAWLER_SRC = APP_DIR.parent / "crawler-service" / "src"
if CRAWLER_SRC.is_dir() and str(CRAWLER_SRC) not in sys.path:
    sys.path.insert(0, str(CRAWLER_SRC))

ROOT = APP_DIR.parent
# 优先同目录资源（发布模式），否则回退项目结构（开发模式）
DB_PATH = os.environ.get(
    "COMIC_DB",
    str(APP_DIR / "comic_demo.db") if (APP_DIR / "comic_demo.db").exists()
    else str(ROOT / "crawler-service" / "comic_demo.db"),
)
DIST_DIR = APP_DIR / "dist" if (APP_DIR / "dist").is_dir() else ROOT / "comic-web" / "dist"

# 存储实现可切换：COMIC_DB_TYPE=mysql 使用 MySQL（Docker ruoyi-mysql），否则 SQLite
DB_TYPE = os.environ.get("COMIC_DB_TYPE", "sqlite").lower()

app = FastAPI(title="漫阅 Comic API", version="0.1.0")
app.add_middleware(
    CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"]
)

if DB_TYPE == "mysql":
    from comic_crawler.mysql_storage import MySQLStorage, MySQLUserStore

    db = MySQLStorage()
else:
    from comic_crawler.storage import SQLiteStorage

    db = SQLiteStorage(db_path=DB_PATH)

# ---------------- 用户中心存储（架构方案 §3.1 user/favorite/history 表） ----------------
# 匿名用户模型：前端首次访问生成 userId（仍服务于「最近阅读/历史」，无需登录）；
# 收藏功能改为登录态：user 表 + JWT 鉴权，多端同步，密码仅存 bcrypt 哈希。
_USER_SCHEMA = """
CREATE TABLE IF NOT EXISTS user (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    username TEXT NOT NULL UNIQUE,
    password_hash TEXT NOT NULL,
    nickname TEXT NOT NULL DEFAULT '',
    avatar_url TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS favorite (
    user_id TEXT NOT NULL,
    comic_id INTEGER NOT NULL,
    created_at TEXT NOT NULL,
    PRIMARY KEY (user_id, comic_id)
);
CREATE TABLE IF NOT EXISTS history (
    user_id TEXT NOT NULL,
    comic_id INTEGER NOT NULL,
    chapter_id INTEGER NOT NULL,
    page_no INTEGER NOT NULL DEFAULT 1,
    read_at TEXT NOT NULL,
    PRIMARY KEY (user_id, comic_id)
);
"""


class UserStore:
    def __init__(self, db_path: str):
        self.db_path = db_path
        with self._conn() as conn:
            conn.executescript(_USER_SCHEMA)

    @contextmanager
    def _conn(self):
        conn = sqlite3.connect(self.db_path)
        try:
            conn.row_factory = sqlite3.Row
            conn.execute("PRAGMA journal_mode=WAL;")
            yield conn
            conn.commit()
        finally:
            conn.close()

    def list_favorites(self, user_id: str) -> list[int]:
        with self._conn() as conn:
            rows = conn.execute(
                "SELECT comic_id FROM favorite WHERE user_id=? ORDER BY created_at DESC",
                (user_id,),
            ).fetchall()
        return [r["comic_id"] for r in rows]

    # ---- 用户账户（登录/注册） ----
    def get_user_by_username(self, username: str) -> sqlite3.Row | None:
        with self._conn() as conn:
            return conn.execute("SELECT * FROM user WHERE username=?", (username,)).fetchone()

    def create_user(self, username: str, password_hash: str, nickname: str) -> sqlite3.Row:
        with self._conn() as conn:
            cur = conn.execute(
                "INSERT INTO user (username, password_hash, nickname, created_at) VALUES (?,?,?,?)",
                (username, password_hash, nickname, datetime.now().isoformat(timespec="seconds")),
            )
            return conn.execute("SELECT * FROM user WHERE id=?", (cur.lastrowid,)).fetchone()

    def get_user(self, user_id: str) -> sqlite3.Row | None:
        with self._conn() as conn:
            return conn.execute("SELECT * FROM user WHERE id=?", (user_id,)).fetchone()

    def is_favorite(self, user_id: str, comic_id: int) -> bool:
        with self._conn() as conn:
            row = conn.execute(
                "SELECT 1 FROM favorite WHERE user_id=? AND comic_id=?",
                (user_id, comic_id),
            ).fetchone()
        return row is not None

    def set_favorite(self, user_id: str, comic_id: int, fav: bool) -> None:
        with self._conn() as conn:
            if fav:
                conn.execute(
                    "INSERT OR IGNORE INTO favorite (user_id, comic_id, created_at) VALUES (?,?,?)",
                    (user_id, comic_id, datetime.now().isoformat(timespec="seconds")),
                )
            else:
                conn.execute(
                    "DELETE FROM favorite WHERE user_id=? AND comic_id=?", (user_id, comic_id)
                )

    def list_history(self, user_id: str) -> list[sqlite3.Row]:
        with self._conn() as conn:
            return conn.execute(
                """SELECT h.comic_id, h.chapter_id, h.page_no, h.read_at,
                          ch.title AS chapter_title
                   FROM history h LEFT JOIN chapter ch ON ch.id = h.chapter_id
                   WHERE h.user_id=? ORDER BY h.read_at DESC LIMIT 50""",
                (user_id,),
            ).fetchall()

    def upsert_history(self, user_id: str, comic_id: int, chapter_id: int, page_no: int) -> None:
        now = datetime.now().isoformat(timespec="seconds")
        with self._conn() as conn:
            conn.execute(
                """INSERT INTO history (user_id, comic_id, chapter_id, page_no, read_at)
                   VALUES (?,?,?,?,?)
                   ON CONFLICT(user_id, comic_id) DO UPDATE SET
                       chapter_id=excluded.chapter_id, page_no=excluded.page_no, read_at=excluded.read_at""",
                (user_id, comic_id, chapter_id, page_no, now),
            )

    def delete_history(self, user_id: str, comic_id: int) -> None:
        with self._conn() as conn:
            conn.execute("DELETE FROM history WHERE user_id=? AND comic_id=?", (user_id, comic_id))


# 用户中心存储：MySQL 版（COMIC_DB_TYPE=mysql）或 SQLite 版（默认）
if DB_TYPE == "mysql":
    from comic_crawler.mysql_storage import MySQLUserStore

    users = MySQLUserStore()
else:
    users = UserStore(db_path=DB_PATH)

# ---------------- 视图计数（内存版；生产环境落库 / Redis 计数器） ----------------
_views: dict[int, int] = {}
_VIEW_BASE = 30000


def comic_views(cid: int) -> int:
    return _VIEW_BASE + (cid * 7919 % 500_000) + _views.get(cid, 0)


# ---------------- 领域模型序列化（蛇形 → 前端驼峰） ----------------
def to_comic(row: dict) -> dict:
    status = row["status"] if row["status"] in ("连载中", "已完结") else "连载中"
    return {
        "id": row["id"],
        "title": row["title"],
        "author": row["author"],
        "category": row["category"],
        "status": status,
        "description": row["description"],
        "cover": f"/api/covers/{row['id']}",
        "latestChapterTitle": row["latest_chapter_title"],
        "chapterCount": row.get("chapter_count", 0),
        "views": comic_views(row["id"]),
        "updatedAt": row["sync_time"],
        "sources": [s for s in (row.get("source") or "").split(",") if s] or ["unknown"],
        "tags": db.get_comic_tags(row["id"]),
    }


def to_chapter(row: dict) -> dict:
    return {
        "id": row["id"],
        "comicId": row["comic_id"],
        "title": row["title"],
        "pageCount": row.get("page_count", 0),
        "orderNo": row["chapter_no"],
        "createdAt": row["sync_time"],
    }


def to_page(row: dict, comic_id: int, chapter_id: int) -> dict:
    return {
        "pageNo": row["page_no"],
        "imageUrl": f"/api/images/{comic_id}/{chapter_id}/{row['page_no']}",
        "width": 720,
        "height": 1020,
    }


# ---------------- SVG 占位图生成（与前端 utils/images.ts 视觉一致） ----------------
def _hue(seed: str) -> int:
    h = 0
    for ch in seed:
        h = (h * 31 + ord(ch)) % 360
    return h


def make_cover_svg(title: str, author: str) -> str:
    hue = _hue(title)
    hue2 = (hue + 40) % 360
    return f'''<svg xmlns="http://www.w3.org/2000/svg" width="300" height="400" viewBox="0 0 300 400">
<defs><linearGradient id="g" x1="0" y1="0" x2="1" y2="1">
<stop offset="0" stop-color="hsl({hue},72%,46%)"/><stop offset="1" stop-color="hsl({hue2},70%,30%)"/>
</linearGradient></defs>
<rect width="300" height="400" fill="url(#g)"/>
<circle cx="230" cy="80" r="70" fill="hsl({hue2},70%,60%)" opacity="0.35"/>
<circle cx="60" cy="330" r="90" fill="hsl({hue},80%,70%)" opacity="0.25"/>
<rect x="24" y="290" width="252" height="4" rx="2" fill="#fff" opacity="0.7"/>
<text x="150" y="340" text-anchor="middle" font-family="'Microsoft YaHei',sans-serif" font-size="30" font-weight="bold" fill="#fff">{title}</text>
<text x="150" y="372" text-anchor="middle" font-family="'Microsoft YaHei',sans-serif" font-size="14" fill="#ffe9e0" opacity="0.9">{author}</text>
</svg>'''


def make_page_svg(comic_title: str, chapter_title: str, page_no: int, total: int) -> str:
    hue = (_hue(comic_title) + page_no * 12) % 360
    panel = f"hsl({(hue + 20) % 360},30%,82%)"
    return f'''<svg xmlns="http://www.w3.org/2000/svg" width="720" height="1020" viewBox="0 0 720 1020">
<rect width="720" height="1020" fill="hsl({hue},22%,94%)"/>
<rect x="36" y="40" width="648" height="420" rx="8" fill="{panel}" stroke="hsl({hue},40%,55%)" stroke-width="4"/>
<rect x="60" y="64" width="200" height="260" rx="6" fill="hsl({(hue + 60) % 360},45%,78%)"/>
<rect x="288" y="64" width="372" height="160" rx="6" fill="hsl({(hue + 120) % 360},45%,80%)"/>
<rect x="288" y="240" width="372" height="84" rx="6" fill="hsl({(hue + 180) % 360},45%,76%)"/>
<rect x="36" y="486" width="648" height="250" rx="8" fill="{panel}" stroke="hsl({hue},40%,55%)" stroke-width="4"/>
<circle cx="500" cy="600" r="70" fill="hsl({(hue + 90) % 360},55%,70%)" opacity="0.8"/>
<rect x="60" y="560" width="180" height="120" rx="6" fill="hsl({(hue + 150) % 360},45%,80%)"/>
<rect x="36" y="762" width="648" height="190" rx="8" fill="{panel}" stroke="hsl({hue},40%,55%)" stroke-width="4"/>
<text x="360" y="900" text-anchor="middle" font-family="'Microsoft YaHei',sans-serif" font-size="26" fill="hsl({hue},50%,35%)">{page_no} / {total}</text>
<text x="360" y="970" text-anchor="middle" font-family="'Microsoft YaHei',sans-serif" font-size="15" fill="#888">{chapter_title} · 第 {page_no} 页（占位图）</text>
</svg>'''


# ---------------- 图片文件探测：已转存真实文件 → 直接返回 ----------------
_IMG_MAGIC: list[tuple[bytes, str]] = [
    (b"\x89PNG\r\n\x1a\n", "image/png"),
    (b"\xff\xd8\xff", "image/jpeg"),
    (b"GIF87a", "image/gif"),
    (b"GIF89a", "image/gif"),
    (b"RIFF", "image/webp"),  # 简化：WEBP 以 RIFF 开头
]
_IMG_EXT = {".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".gif": "image/gif", ".webp": "image/webp", ".svg": "image/svg+xml"}


def _resolve_image_root() -> Path | None:
    """定位图库根目录（image_store）。

    优先级：env COMIC_IMAGE_ROOT > 发布模式 main.py 同目录 / DB 同目录 > 开发模式项目结构。
    DB 只存图库内相对 key（如 covers/26.jpg），根目录随部署环境解析，整库可随项目移动。
    """
    env = os.environ.get("COMIC_IMAGE_ROOT")
    if env:
        p = Path(env)
        if p.is_dir():
            return p.resolve()
    candidates: list[Path] = []
    img_dir = APP_DIR / "image_store"
    if img_dir.is_dir():
        candidates.append(img_dir)
    dbp = Path(DB_PATH)
    img_dir = dbp.parent / "image_store"
    if img_dir.is_dir():
        candidates.append(img_dir)
    if CRAWLER_SRC.is_dir():
        img_dir = CRAWLER_SRC.parent / "image_store"
        if img_dir.is_dir():
            candidates.append(img_dir)
    for c in candidates:
        if c.is_dir():
            return c.resolve()
    return None


_IMAGE_ROOT = _resolve_image_root()


def _read_image_file(candidate: str) -> tuple[bytes, str] | None:
    """从本地路径、file:// URI 或图库内相对 key 读图片字节；仅接受真正的图片内容。"""
    if not candidate:
        return None
    p = candidate
    if p.startswith("file://"):
        p = p[len("file://"):]
        if os.name == "nt" and p.startswith("/") and len(p) > 2 and p[2] == ":":
            p = p[1:]
    elif not p.startswith(("http://", "https://")) and not os.path.isabs(p):
        # 图库内相对 key（如 covers/26.jpg、comic/26/34/001.jpg）：按图库根拼接
        if _IMAGE_ROOT is None:
            return None
        p = str(_IMAGE_ROOT / p.lstrip("/"))
    path = Path(p)
    if not path.is_file():
        return None
    data = path.read_bytes()
    for magic, mime in _IMG_MAGIC:
        if data.startswith(magic):
            return data, mime
    # SVG 文本
    head = data[:512].lstrip().lower()
    if head.startswith(b"<svg") or head.startswith(b"<?xml"):
        return data, "image/svg+xml"
    return None


# ---------------- API 端点 ----------------
def _ok(data, message: str = "ok") -> dict:
    return {"code": 0, "message": message, "data": data}


# ---------------- 用户认证（JWT + bcrypt） ----------------
# 演示用途密钥；生产环境用环境变量注入强随机值。
_JWT_SECRET = os.environ.get("COMIC_JWT_SECRET", "comic-demo-secret-change-me")
_JWT_ALGO = "HS256"
_JWT_EXP_HOURS = 24 * 7  # 7 天
_bearer = HTTPBearer(auto_error=False)


def _hash_password(raw: str) -> str:
    return bcrypt.hashpw(raw.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")


def _verify_password(raw: str, hashed: str) -> bool:
    try:
        return bcrypt.checkpw(raw.encode("utf-8"), hashed.encode("utf-8"))
    except (ValueError, TypeError):
        return False


def _make_token(user_id: int, username: str) -> str:
    now = datetime.now()
    payload = {
        "sub": str(user_id),
        "username": username,
        "iat": int(now.timestamp()),
        "exp": int((now + timedelta(hours=_JWT_EXP_HOURS)).timestamp()),
    }
    return jwt.encode(payload, _JWT_SECRET, algorithm=_JWT_ALGO)


def _decode_token(token: str) -> dict:
    """解码并校验 token；无效/过期抛 401。"""
    try:
        payload = jwt.decode(token, _JWT_SECRET, algorithms=[_JWT_ALGO])
    except jwt.ExpiredSignatureError:
        raise HTTPException(status_code=401, detail="token expired")
    except jwt.InvalidTokenError:
        raise HTTPException(status_code=401, detail="invalid token")
    return payload


def get_current_user(cred: HTTPAuthorizationCredentials | None = Depends(_bearer)) -> dict:
    """从 Authorization: Bearer <token> 解析当前登录用户。"""
    if cred is None:
        raise HTTPException(status_code=401, detail="not authenticated")
    payload = _decode_token(cred.credentials)
    user = users.get_user(payload.get("sub", ""))
    if not user:
        raise HTTPException(status_code=401, detail="user not found")
    return user


class RegisterBody(BaseModel):
    username: str
    password: str
    nickname: str = ""


class LoginBody(BaseModel):
    username: str
    password: str


class HistoryPut(BaseModel):
    comicId: int
    chapterId: int
    pageNo: int = 1


# ---------------- 用户认证端点（注册 / 登录 / 当前用户） ----------------
def _user_out(user) -> dict:
    return {
        "id": user["id"],
        "username": user["username"],
        "nickname": user["nickname"] or user["username"],
        "createdAt": user["created_at"],
    }


@app.post("/api/auth/register")
def register(body: RegisterBody):
    username = body.username.strip()
    if not (3 <= len(username) <= 32):
        raise HTTPException(status_code=400, detail="用户名长度需为 3-32 个字符")
    if len(body.password) < 6:
        raise HTTPException(status_code=400, detail="密码长度至少 6 位")
    if users.get_user_by_username(username):
        raise HTTPException(status_code=409, detail="用户名已存在")
    user = users.create_user(username, _hash_password(body.password), body.nickname.strip())
    return _ok({"token": _make_token(user["id"], user["username"]), "user": _user_out(user)}, "register success")


@app.post("/api/auth/login")
def login(body: LoginBody):
    user = users.get_user_by_username(body.username.strip())
    if not user or not _verify_password(body.password, user["password_hash"]):
        raise HTTPException(status_code=401, detail="用户名或密码错误")
    return _ok({"token": _make_token(user["id"], user["username"]), "user": _user_out(user)}, "login success")


@app.get("/api/auth/me")
def me(user: dict = Depends(get_current_user)):
    return _ok(_user_out(user))


@app.get("/api/health")
def health():
    return _ok({**db.stats(), "categories": len(db.get_categories()), "views": sum(_views.values())})


@app.get("/api/categories")
def categories():
    items = db.get_categories()
    return _ok([{"name": "全部", "count": sum(i["count"] for i in items)}] + items)


@app.get("/api/comics")
def comics(category: str | None = None, keyword: str | None = None, sort: str = "updated", page: int = 1, page_size: int = 12):
    page = max(1, page)
    page_size = min(max(1, page_size), 50)
    rows, total = db.list_comics(category=category, keyword=keyword, sort=sort, page=page, page_size=page_size)
    return _ok({"items": [to_comic(r) for r in rows], "total": total, "page": page, "pageSize": page_size})


@app.get("/api/comics/{comic_id}")
def comic_detail(comic_id: int):
    row = db.get_comic(comic_id)
    if not row:
        raise HTTPException(status_code=404, detail="comic not found")
    _views[comic_id] = _views.get(comic_id, 0) + 1  # 详情访问计数（演示热门榜）
    return _ok(to_comic(row))


@app.get("/api/comics/{comic_id}/chapters")
def chapters(comic_id: int):
    rows = db.get_chapters(comic_id)
    return _ok([to_chapter(r) for r in rows])


@app.get("/api/chapters/{chapter_id}/pages")
def chapter_pages(chapter_id: int):
    ch = db.get_chapter(chapter_id)
    if not ch:
        raise HTTPException(status_code=404, detail="chapter not found")
    rows = db.get_pages(chapter_id)
    return _ok([to_page(r, ch["comic_id"], chapter_id) for r in rows])


# ---------------- 用户中心 ----------------
# 收藏：登录态（JWT）；历史/最近阅读：匿名 userId（无需登录）。


@app.get("/api/users/{user_id}/favorites")
def favorites(user_id: str, user: dict = Depends(get_current_user)):
    """收藏列表：需登录。user_id 参数保留用于路由兼容，实际以 token 身份为准。"""
    user_id = str(user["id"])
    items = []
    for cid in users.list_favorites(user_id):
        row = db.get_comic(cid)
        if row:
            items.append(to_comic(row))
    return _ok(items)


@app.get("/api/users/{user_id}/favorites/{comic_id}")
def favorite_state(user_id: str, comic_id: int, user: dict = Depends(get_current_user)):
    return _ok({"favorited": users.is_favorite(str(user["id"]), comic_id)})


@app.put("/api/users/{user_id}/favorites/{comic_id}")
def add_favorite(user_id: str, comic_id: int, user: dict = Depends(get_current_user)):
    if not db.get_comic(comic_id):
        raise HTTPException(status_code=404, detail="comic not found")
    users.set_favorite(str(user["id"]), comic_id, True)
    return _ok({"favorited": True})


@app.delete("/api/users/{user_id}/favorites/{comic_id}")
def remove_favorite(user_id: str, comic_id: int, user: dict = Depends(get_current_user)):
    users.set_favorite(str(user["id"]), comic_id, False)
    return _ok({"favorited": False})


@app.get("/api/users/{user_id}/history")
def history(user_id: str):
    items = []
    for r in users.list_history(user_id):
        comic = db.get_comic(r["comic_id"])
        if not comic:
            continue
        items.append({
            "comicId": r["comic_id"],
            "chapterId": r["chapter_id"],
            "pageNo": r["page_no"],
            "readAt": r["read_at"],
            "chapterTitle": r["chapter_title"],
            "comic": to_comic(comic),
        })
    return _ok(items)


@app.put("/api/users/{user_id}/history")
def put_history(user_id: str, body: HistoryPut):
    users.upsert_history(user_id, body.comicId, body.chapterId, body.pageNo)
    return _ok(None, "history updated")


@app.delete("/api/users/{user_id}/history/{comic_id}")
def remove_history(user_id: str, comic_id: int):
    users.delete_history(user_id, comic_id)
    return _ok(None, "history removed")


@app.get("/api/covers/{comic_id}")
def cover(comic_id: int):
    row = db.get_comic(comic_id)
    if not row:
        raise HTTPException(status_code=404, detail="comic not found")
    img = _read_image_file(row.get("cover_url") or "")
    if img:
        return Response(content=img[0], media_type=img[1])
    return Response(content=make_cover_svg(row["title"], row["author"]), media_type="image/svg+xml")


@app.get("/api/images/{comic_id}/{chapter_id}/{page_no}")
def page_image(comic_id: int, chapter_id: int, page_no: int):
    ch = db.get_chapter(chapter_id)
    if not ch or ch["comic_id"] != comic_id:
        raise HTTPException(status_code=404, detail="chapter not found")
    rows = db.get_pages(chapter_id)
    row = next((p for p in rows if p["page_no"] == page_no), None)
    if not row:
        raise HTTPException(status_code=404, detail="page not found")
    # 优先：已转存的 OSS 文件（真实图片）
    img = _read_image_file(row.get("oss_url") or "") or _read_image_file(row.get("source_url") or "")
    if img:
        return Response(content=img[0], media_type=img[1])
    # 回退：生成占位图（演示环境）
    comic = db.get_comic(comic_id)
    return Response(
        content=make_page_svg(comic["title"] if comic else "漫画", ch["title"], page_no, len(rows)),
        media_type="image/svg+xml",
    )


# ---------------- 托管前端构建产物（同源部署） ----------------
if DIST_DIR.is_dir():
    app.mount("/", StaticFiles(directory=str(DIST_DIR), html=True), name="web")


if __name__ == "__main__":
    uvicorn.run("main:app", host="127.0.0.1", port=8000, reload=False)
