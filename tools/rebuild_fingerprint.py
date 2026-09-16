"""一次性迁移：按当前归一化规则**重建 `comic.fingerprint`**。

背景：`fingerprint`（归一化标题 + 作者）是"这几行可能是同一部作品"的**观测标记**，
只在写入/更新作品时算一次就固化在库里；归一化规则一旦变化（历史上加过、又撤过繁简折叠），
历史行的指纹就与新规则不一致，观测就失真了。

⚠️ **指纹不参与判重**（判重只看 `(source, source_comic_id)`，跨源不合并 —— 用户 2026-09-16
决策，见 `docs/architecture.md` §2.3），所以本脚本**只对齐这个观测字段**，
不合并、不删除任何作品行。

本脚本按 `build_fingerprint(title, author)` 重算所有作品指纹：
- 只更新**变了**的行；没变的一行不碰（幂等，可重复运行）；
- 顺带报告"同指纹多行"（同一部作品来自不同源）—— 这是**预期**状态，仅列出供人工判断；
- 一个事务里做完，失败自动回滚。

**可回滚**：执行前把「受影响行 + 旧指纹」写成 `backup/fingerprint_before_rebuild_<时间戳>.sql`，
文件里就是一组可反向执行的 `UPDATE comic SET fingerprint=...`。

用法（在 comic 仓库根目录）：
    cd crawler-service && .venv/Scripts/python.exe ../tools/rebuild_fingerprint.py
（脚本自己把 `crawler-service/src` 加进 `sys.path`，不需要设 PYTHONPATH。）
连接 MySQL（`COMIC_MYSQL_*` 环境变量 → `deploy/.env` → 默认值，与其它运维脚本同一套）。
"""

from __future__ import annotations

import datetime
import os
import sys
from pathlib import Path

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "crawler-service", "src"))

import pymysql  # noqa: E402

from comic_crawler.fingerprint import build_fingerprint  # noqa: E402
from comic_crawler.storage.mysql import MySQLStorage  # noqa: E402

BACKUP_DIR = Path(__file__).resolve().parents[1] / "backup"


def main() -> int:
    storage = MySQLStorage()
    dsn = dict(storage.dsn)
    dsn["autocommit"] = False          # 整批更新放一个事务里
    conn = pymysql.connect(**dsn)
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT id, title, author, source, fingerprint FROM comic ORDER BY id")
            rows = list(cur.fetchall())

            plan: list[tuple[int, str, str, str]] = []   # (id, title, 旧指纹, 新指纹)
            unchanged = 0
            for r in rows:
                new_fp = build_fingerprint(r["title"], r["author"] or "")
                if new_fp == r["fingerprint"]:
                    unchanged += 1
                else:
                    plan.append((int(r["id"]), r["title"], r["fingerprint"], new_fp))

            BACKUP_DIR.mkdir(parents=True, exist_ok=True)
            stamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
            backup = BACKUP_DIR / f"fingerprint_before_rebuild_{stamp}.sql"
            with backup.open("w", encoding="utf-8", newline="\n") as out:
                out.write("-- ============================================================\n")
                out.write("-- 回滚用：comic.fingerprint 重建前的旧值\n")
                out.write(f"-- 生成时间: {datetime.datetime.now().isoformat(timespec='seconds')}\n")
                out.write("-- 直接执行即可改回原样（只动 fingerprint 一列）\n")
                out.write("-- ============================================================\n")
                for cid, title, old_fp, _new_fp in plan:
                    out.write(
                        f"UPDATE comic SET fingerprint = '{old_fp}' WHERE id = {cid};"
                        f"  -- {title.replace(chr(39), chr(39) * 2)}\n"
                    )

            print(f"备份: {backup.name}")
            print(f"共 {len(rows)} 部：待重建 {len(plan)} / 未变 {unchanged}")

            for cid, _title, _old, new_fp in plan:
                cur.execute("UPDATE comic SET fingerprint = %s WHERE id = %s", (new_fp, cid))
            conn.commit()
            for cid, title, old_fp, new_fp in plan:
                print(f"   #{cid:<3} {title!r:<34} {old_fp} -> {new_fp}")
            if not plan:
                print("   （没有需要重建的行）")

            # 观测：同指纹多行 = 同一部作品来自不同源（跨源不合并，属预期）
            cur.execute(
                """SELECT fingerprint, COUNT(*) AS n,
                          GROUP_CONCAT(CONCAT(source, '#', id) ORDER BY source) AS rows_
                   FROM comic GROUP BY fingerprint HAVING n > 1 ORDER BY n DESC"""
            )
            dup = list(cur.fetchall())
            cur.execute("SELECT COUNT(*) AS c FROM comic")
            total = int(cur.fetchone()["c"])
    finally:
        conn.close()

    print(f"\n结果：comic 共 {total} 部，指纹已按当前规则对齐（可重跑，第二次应显示「待重建 0」）")
    print(f"「同指纹多行」（同一部作品来自不同源）{len(dup)} 组 —— 跨源不合并，属预期：")
    for r in dup:
        print(f"   {r['fingerprint']}  ×{r['n']}  ← {r['rows_']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
