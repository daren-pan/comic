"""一次性迁移：给 `user` 表加 `role` 列（管理台鉴权），并把**超级管理员**定下来。

### 角色三档（见 `docs/auth.md` §8）

| 值 | 名字 | 能做什么 |
|---|---|---|
| `superadmin` | 超级管理员 | 管理台 + 日志 + **授权页**；**全库唯一** |
| `admin` | 普通管理员 | 管理台 + 日志；**进不了授权页** |
| `user` | 普通用户（默认） | 无管理台权限 |

背景：管理台 `/api/admin/*` 原先**完全免登录**（router 上无任何依赖），
是 `docs/deploy.md`「上线前必做」里挂着的已知项。现在改为角色制。

### 本脚本做三件事（都幂等）

1. **补列**：没有 `role` 就加（DDL 真源是 `crawler-service/sql/mysql_schema.sql`，新库建表本来就带）；
2. **定超管**：库里**没有任何 `superadmin`** 时，把**最早的特权用户**（`admin` 里 id 最小的）
   提升为 `superadmin`；连特权用户都没有，就提升**最早注册的用户** ——
   否则升级完没人能进授权页，等于把自己锁在外面；
3. **可选转移**：`--superadmin <用户名>` 把指定用户设为超管，**并把原超管降为普通管理员**
   （保证"超管全库唯一"）。这是**转移/修复通道**，要服务器权限，正常不常用。

### 幂等与回滚

- 幂等：列已存在则跳过加列；已有超管则跳过提升；`--superadmin` 指定的人已是超管则无改动。
- 回滚（回到"管理台免登录"的旧状态，仅限本地/内网）：
      UPDATE user SET role = 'user' WHERE role IN ('superadmin','admin');
      ALTER TABLE user DROP COLUMN role;

用法（在 comic 仓库根目录）：
    cd crawler-service && .venv/Scripts/python.exe ../tools/add_user_role.py
    cd crawler-service && .venv/Scripts/python.exe ../tools/add_user_role.py --superadmin caimf
连接参数走 `COMIC_MYSQL_*` 环境变量 → 仓库根 `deploy/.env` → 默认值（与其它运维脚本同一套）。
"""

from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "crawler-service", "src"))

from comic_crawler.storage.mysql import MySQLStorage  # noqa: E402

TABLE = "user"
COLUMN = "role"
ROLE_SUPERADMIN = "superadmin"
ROLE_ADMIN = "admin"
ROLE_USER = "user"
PRIVILEGED = (ROLE_SUPERADMIN, ROLE_ADMIN)


def _query(store: MySQLStorage, sql: str, params: tuple = ()) -> list[dict]:
    with store._conn() as conn:
        with conn.cursor() as cur:
            cur.execute(sql, params)
            return list(cur.fetchall())


def _exec(store: MySQLStorage, sql: str, params: tuple = ()) -> int:
    with store._conn() as conn:
        with conn.cursor() as cur:
            cur.execute(sql, params)
            return cur.rowcount


def _columns(store: MySQLStorage) -> list[str]:
    rows = _query(
        store,
        """SELECT COLUMN_NAME AS c FROM information_schema.COLUMNS
           WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = %s
           ORDER BY ORDINAL_POSITION""",
        (TABLE,),
    )
    return [str(r["c"]) for r in rows]


def _superadmins(store: MySQLStorage) -> list[dict]:
    return _query(
        store,
        f"SELECT id, username FROM {TABLE} WHERE {COLUMN} = %s ORDER BY id",
        (ROLE_SUPERADMIN,),
    )


def _promote(store: MySQLStorage, user_id: int, role: str) -> None:
    _exec(store, f"UPDATE {TABLE} SET {COLUMN} = %s WHERE id = %s", (role, user_id))


def main(argv: list[str]) -> int:
    target_username = ""
    if "--superadmin" in argv:
        i = argv.index("--superadmin")
        if i + 1 >= len(argv):
            print("  ❌ --superadmin 后面要跟用户名，例如 --superadmin caimf")
            return 1
        target_username = argv[i + 1].strip()

    store = MySQLStorage()

    cols = _columns(store)
    if not cols:
        print(f"  ❌ 库里没有 {TABLE} 表 —— 先建库（scripts/init_mysql.sh）或用全新库部署")
        return 1
    if COLUMN in cols:
        print(f"  = {TABLE}.{COLUMN} 已存在，跳过加列")
    else:
        _exec(
            store,
            f"ALTER TABLE {TABLE} ADD COLUMN {COLUMN} VARCHAR(32) "
            f"NOT NULL DEFAULT '{ROLE_USER}' AFTER avatar_url",
        )
        print(f"  + 已加列 {TABLE}.{COLUMN}（默认 '{ROLE_USER}'）")

    # ---- 3. 显式转移（可选的运维通道）----
    if target_username:
        rows = _query(store, f"SELECT id FROM {TABLE} WHERE username = %s", (target_username,))
        if not rows:
            print(f"  ❌ 找不到用户 {target_username}")
            return 1
        tid = int(rows[0]["id"])
        others = [a for a in _superadmins(store) if int(a["id"]) != tid]
        for a in others:
            _promote(store, int(a["id"]), ROLE_ADMIN)
        _promote(store, tid, ROLE_SUPERADMIN)
        if others:
            print(
                f"  ⚠️ 已把 {target_username}(id={tid}) 设为超级管理员；"
                f"原超管 {', '.join(a['username'] for a in others)} 降为普通管理员"
            )
        else:
            print(f"  + 已把 {target_username}(id={tid}) 设为超级管理员")

    # ---- 2. 定超管（库里一个超管都没有时兜底，防锁死）----
    if not _superadmins(store):
        total = int(_query(store, f"SELECT COUNT(*) AS n FROM {TABLE}")[0]["n"])
        if total:
            first = _query(
                store,
                f"""SELECT id, username FROM {TABLE} WHERE {COLUMN} IN ('superadmin','admin')
                    ORDER BY id LIMIT 1""",
            )[0]
            _promote(store, int(first["id"]), ROLE_SUPERADMIN)
            print(
                f"  ⚠️ 库里没有任何超级管理员 → 已把**最早的特权用户**提升为超管："
                f"id={first['id']} username={first['username']}"
            )

    # ---- 复查：角色分布 ----
    dist = _query(
        store, f"SELECT {COLUMN} AS r, COUNT(*) AS n FROM {TABLE} GROUP BY {COLUMN} ORDER BY {COLUMN}"
    )
    total = int(_query(store, f"SELECT COUNT(*) AS n FROM {TABLE}")[0]["n"])
    print(f"\n复查：{TABLE} 共 {total} 个用户")
    for d in dist:
        print(f"  · {d['r']:<11} {d['n']}")
    for a in _superadmins(store):
        print(f"  超级管理员：id={a['id']} {a['username']}（全库唯一，转移用 --superadmin <用户名>）")
    if not total:
        print("  （库里还没有用户 —— 注册的第一个用户会自动成为超级管理员）")
    print(f"\n列：{', '.join(_columns(store))}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
