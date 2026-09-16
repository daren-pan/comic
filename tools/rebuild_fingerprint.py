"""一次性迁移：按当前归一化规则**重建 `comic.fingerprint`**。

背景：指纹（`comic_crawler.fingerprint`）是跨源去重的唯一依据，只在**写入/更新作品时**算一次
并被 UNIQUE 约束固化在库里。归一化规则一旦变化（本次是加入**繁转简**），历史行的指纹就
与新规则不一致 —— 表现为新采集的简体写法作品与库里已有的繁体写法作品**各自成行**。

本脚本按 `build_fingerprint(title, author)` 重算所有作品指纹：
- 只更新**变了**的行；没变的一行不碰（幂等，可重复运行）；
- 更新分两阶段（先写成 `tmp-<id>` 再写成最终值）避免撞上 `uk_fingerprint` 的**瞬时冲突**；
  整段在一个事务里，失败自动回滚；

⚠️ **冲突检测**：折叠后可能有两行**指向同一个新指纹**（说明它们本就是同一部作品、只是当初
一繁一简没认出来）。合并两条作品记录是另一件事（涉及 chapter / favorite / history 的搬迁），
本脚本**只报告不合并**，这类行保持原指纹不动，由人决定怎么处理。

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
    dsn["autocommit"] = False          # 两阶段更新要在一个事务里
    conn = pymysql.connect(**dsn)
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT id, title, author, fingerprint FROM comic ORDER BY id")
            rows = list(cur.fetchall())

            plan: list[tuple[int, str, str, str]] = []   # (id, title, 旧指纹, 新指纹)
            unchanged = 0
            for r in rows:
                new_fp = build_fingerprint(r["title"], r["author"] or "")
                if new_fp == r["fingerprint"]:
                    unchanged += 1
                else:
                    plan.append((int(r["id"]), r["title"], r["fingerprint"], new_fp))

            # 冲突：多个 id 落到同一新指纹（跨源重复），或新指纹已被别的行占着
            targets: dict[str, list[int]] = {}
            for cid, _t, _old, new_fp in plan:
                targets.setdefault(new_fp, []).append(cid)
            keep_old = {r["fingerprint"] for r in rows} - {p[2] for p in plan}
            conflicted = {fp for fp, ids in targets.items() if len(ids) > 1 or fp in keep_old}
            safe = [p for p in plan if p[3] not in conflicted]
            blocked = [p for p in plan if p[3] in conflicted]

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
                    t = title.replace("'", "''")
                    out.write(f"UPDATE comic SET fingerprint = '{old_fp}' WHERE id = {cid};  -- {t}\n")

            print(f"备份: {backup.name}")
            print(f"共 {len(rows)} 部：待重建 {len(plan)} / 未变 {unchanged}"
                  + (f" / 因冲突跳过 {len(blocked)}" if blocked else ""))

            if safe:
                ids = ", ".join(str(p[0]) for p in safe)
                cur.execute(f"UPDATE comic SET fingerprint = CONCAT('tmp-', id) WHERE id IN ({ids})")
                for cid, _title, _old, new_fp in safe:
                    cur.execute("UPDATE comic SET fingerprint = %s WHERE id = %s", (new_fp, cid))
                conn.commit()
                for cid, title, old_fp, new_fp in safe:
                    print(f"   #{cid:<3} {title!r:<34} {old_fp} -> {new_fp}")
            else:
                conn.commit()   # 只落备份
                print("   （没有需要重建的行）")

            if blocked:
                print("\n⚠️ 以下行折叠后与别的行**同一指纹**（本就是同一部作品，只是当初没认出来），")
                print("   本脚本不合并、保持原状，请人工决定保留哪一条：")
                for fp, ids in sorted(targets.items()):
                    if fp in conflicted:
                        for cid, title, old_fp, _new_fp in plan:
                            if cid in ids:
                                print(f"   #{cid:<3} {title!r:<34} {old_fp} -> 将与 {ids} 撞到 {fp}")

            cur.execute("SELECT COUNT(*) AS n FROM comic")
            total = int(cur.fetchone()["n"])
    finally:
        conn.close()

    print(f"\n结果：comic 共 {total} 部，指纹已按当前规则对齐（同名可重跑，第二次应显示「待重建 0」）")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
