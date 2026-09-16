"""一次性迁移：去掉 `comic.fingerprint` 的**唯一约束**，改成普通索引。

背景（用户 2026-09-16 决策，见 `docs/architecture.md` §2.3）：
**跨源不再合并** —— 判重只看 `(source, source_comic_id)`。同一部作品在别的源收过时，
本次要**新增一行**，而 `uk_fingerprint` 唯一约束会直接让 INSERT 报重复键错误，
所以必须先去约束。

为什么不是删列：`fingerprint` 保留为"这几行可能是同一部作品"的**观测标记**
（归一化标题 + 作者），供运维查重；只是不再参与判重。索引保留普通索引即可
（`get_comic_id_by_fingerprint` 已删除，新代码不再按指纹查）。

**幂等**：可重复运行 —— 已经没有 `uk_fingerprint` 时直接跳过。
**⚠️ 回滚有限制**：唯一约束一旦去掉，库内可能已经出现同指纹的多行（正是这次改动的目的），
此时回滚（重建 UNIQUE）会因重复值失败 —— 必须先人工处理重复行：
    ALTER TABLE comic DROP INDEX idx_comic_fingerprint,
                      ADD UNIQUE KEY uk_fingerprint (fingerprint);

用法（在 comic 仓库根目录）：
    cd crawler-service && .venv/Scripts/python.exe ../tools/drop_fingerprint_unique.py
连接参数走 `COMIC_MYSQL_*` 环境变量 → 仓库根 `deploy/.env` → 默认值（与其它运维脚本同一套）。
"""

from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "crawler-service", "src"))

from comic_crawler.storage.mysql import MySQLStorage  # noqa: E402

TABLE = "comic"
UNIQUE_NAME = "uk_fingerprint"
PLAIN_NAME = "idx_comic_fingerprint"


def _index_names(store: MySQLStorage) -> set[str]:
    with store._conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """SELECT DISTINCT INDEX_NAME AS n FROM information_schema.STATISTICS
                   WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = %s""",
                (TABLE,),
            )
            return {str(r["n"]) for r in cur.fetchall()}


def _query(store: MySQLStorage, sql: str) -> list[dict]:
    with store._conn() as conn:
        with conn.cursor() as cur:
            cur.execute(sql)
            return list(cur.fetchall())


def main() -> int:
    store = MySQLStorage()
    names = _index_names(store)

    if UNIQUE_NAME not in names:
        print(f"  = {TABLE}.{UNIQUE_NAME} 不存在（已经迁移过或无此约束），跳过")
    else:
        with store._conn() as conn:
            with conn.cursor() as cur:
                cur.execute(f"ALTER TABLE {TABLE} DROP INDEX {UNIQUE_NAME}")  # noqa: S608
        print(f"  - 已删除唯一约束 {TABLE}.{UNIQUE_NAME}")

        if PLAIN_NAME in _index_names(store):
            print(f"  = {TABLE}.{PLAIN_NAME} 已存在，不重复建")
        else:
            with store._conn() as conn:
                with conn.cursor() as cur:
                    cur.execute(
                        f"ALTER TABLE {TABLE} ADD INDEX {PLAIN_NAME} (fingerprint)"  # noqa: S608
                    )
            print(f"  + 已建立普通索引 {TABLE}.{PLAIN_NAME} (fingerprint)")

    # 现状复查：指纹相同的行数（= 库里"同名同作者、来自不同源"的作品，属预期）
    after = _index_names(store)
    print("\n复查：")
    print(f"  [{'OK' if PLAIN_NAME in after else '缺失'}] {TABLE}.{PLAIN_NAME} (fingerprint) 普通索引")
    print(f"  [{'已去掉 ✓' if UNIQUE_NAME not in after else '⚠️ 仍存在'}] {TABLE}.{UNIQUE_NAME} 唯一约束")

    dup = _query(
        store,
        """SELECT fingerprint, COUNT(*) AS n, GROUP_CONCAT(source ORDER BY source) AS sources
           FROM comic GROUP BY fingerprint HAVING n > 1 ORDER BY n DESC""",
    )
    total = int(_query(store, "SELECT COUNT(*) AS c FROM comic")[0]["c"])
    print(f"\ncomic 共 {total} 行；其中「同指纹多行」（同一部作品来自不同源）{len(dup)} 组：")
    for r in dup:
        print(f"    {r['fingerprint']}  ×{r['n']}  ← {r['sources']}")
    print("\n（跨源不再合并，这些多行是**预期**结果：各记各自的章节进度。）")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
