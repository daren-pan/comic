"""一次性迁移：把库内**已有**标签按中文同义词词表统一为规范名。

背景：标签归一化（`comic_crawler.taxonomy`）在**写入时**生效；但库里此前写入的标签
（mangadex 的英文、zaimanhua 的中文、weebcentral 的英文）仍是各源原文，本脚本按**同一张词表**
把它们合并到规范名，使历史数据与新采集的数据一致。

逐个待归一的标签：
1. `INSERT IGNORE` 建出规范名标签行（已存在则复用其 id）；
2. 删除与规范行**冲突**的关联 —— 同一部作品同时挂 `Comedy` 与 `搞笑` 时，
   `uk_comic_tag(comic_id, tag_id)` 会挡住后面的 UPDATE；
3. 其余关联 UPDATE 指到规范行；
4. 原标签行若已无任何关联则删除（清理）。

**幂等**：可重复运行 —— 第二次跑时已无「需归一」的标签。
**可回滚**：执行前把 `tag` 与 `comic_tag` 全表导出为 INSERT 语句到 `backup/`（两表都很小）。

用法（在 comic 仓库根目录）：
    cd crawler-service && PYTHONPATH=src python ../tools/normalize_tags.py
连接 MySQL（`COMIC_MYSQL_*` 环境变量控制连接参数）。
"""

from __future__ import annotations

import datetime
import decimal
import io
import os
import sys
from pathlib import Path

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "crawler-service", "src"))

from comic_crawler.storage.mysql import MySQLStorage  # noqa: E402
from comic_crawler.taxonomy import canonical_tag  # noqa: E402

BACKUP_DIR = Path(__file__).resolve().parents[1] / "backup"


def _lit(v: object) -> str:
    """Python 值 -> SQL 字面量（导出 INSERT 用）。"""
    if v is None:
        return "NULL"
    if isinstance(v, bool):
        return "1" if v else "0"
    if isinstance(v, (int, float, decimal.Decimal)):
        return str(v)
    if isinstance(v, (datetime.datetime, datetime.date)):
        return "'" + v.isoformat(sep=" ") + "'"
    return "'" + str(v).replace("\\", "\\\\").replace("'", "''") + "'"


def _dump(cur, table: str, out: io.TextIOWrapper) -> int:
    cur.execute(f"SELECT * FROM {table}")
    rows = cur.fetchall()
    out.write(f"\n-- {table}: {len(rows)} 行\n")
    for r in rows:
        cols = list(r.keys())
        out.write(
            f"INSERT INTO `{table}` ({', '.join('`' + c + '`' for c in cols)}) VALUES "
            f"({', '.join(_lit(r[c]) for c in cols)});\n"
        )
    return len(rows)


def main() -> int:
    BACKUP_DIR.mkdir(parents=True, exist_ok=True)
    stamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    backup = BACKUP_DIR / f"tags_before_normalize_{stamp}.sql"

    storage = MySQLStorage()
    with storage._conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """SELECT t.id, t.name, COUNT(ct.id) AS refs
                   FROM tag t LEFT JOIN comic_tag ct ON ct.tag_id = t.id
                   GROUP BY t.id, t.name ORDER BY t.id"""
            )
            rows = cur.fetchall()

            todo = []
            kept = []
            for r in rows:
                canon = canonical_tag(r["name"])
                if canon and canon != r["name"]:
                    todo.append((int(r["id"]), r["name"], canon, int(r["refs"])))
                else:
                    kept.append(r["name"])

            # 备份（可回滚：先 INSERT 两表，再重建关联）
            with io.open(backup, "w", encoding="utf-8", newline="\n") as out:
                out.write("-- ============================================================\n")
                out.write("-- 回滚用备份：标签归一化迁移前的 tag / comic_tag 全表\n")
                out.write(f"-- 生成时间: {datetime.datetime.now().isoformat(timespec='seconds')}\n")
                out.write("-- 回滚顺序：先 DELETE FROM comic_tag; DELETE FROM tag;\n")
                out.write("--           再按本文件顺序执行 INSERT（tag 在前、comic_tag 在后）\n")
                out.write("-- ============================================================\n")
                n_tag = _dump(cur, "tag", out)
                n_ct = _dump(cur, "comic_tag", out)

            print(f"备份: {backup.name}  (tag {n_tag} 行 / comic_tag {n_ct} 行)")
            print(f"待归一标签 {len(todo)} 个，保留原文 {len(kept)} 个")

            moved = 0
            removed = 0
            for old_id, old_name, canon, refs in todo:
                cur.execute("INSERT IGNORE INTO tag (name) VALUES (%s)", (canon,))
                cur.execute("SELECT id FROM tag WHERE name = %s", (canon,))
                new_id = int(cur.fetchone()["id"])
                if new_id == old_id:      # 理论不可达（canon != old_name）
                    continue
                # 同一部作品同时挂了旧标签与规范标签时，先删旧关联（否则 uk_comic_tag 冲突）
                cur.execute(
                    """DELETE ct FROM comic_tag ct
                       JOIN comic_tag ct2
                         ON ct2.comic_id = ct.comic_id AND ct2.tag_id = %s
                       WHERE ct.tag_id = %s""",
                    (new_id, old_id),
                )
                cur.execute(
                    "UPDATE comic_tag SET tag_id = %s WHERE tag_id = %s", (new_id, old_id)
                )
                moved += cur.rowcount
                cur.execute("SELECT COUNT(*) AS n FROM comic_tag WHERE tag_id = %s", (old_id,))
                if int(cur.fetchone()["n"]) == 0:
                    cur.execute("DELETE FROM tag WHERE id = %s", (old_id,))
                    removed += 1
                    print(f"   {old_name!r:>28} → {canon!r}  (原 {refs} 部)")
                else:
                    print(f"   {old_name!r:>28} → {canon!r}  ⚠️ 仍有残留关联，保留标签行")

            cur.execute("SELECT COUNT(*) AS n FROM tag")
            tag_total = int(cur.fetchone()["n"])
            cur.execute("SELECT COUNT(*) AS n FROM comic_tag")
            ct_total = int(cur.fetchone()["n"])

            cur.execute(
                """SELECT t.name, COUNT(DISTINCT ct.comic_id) AS comics
                   FROM tag t JOIN comic_tag ct ON ct.tag_id = t.id
                   GROUP BY t.id, t.name ORDER BY comics DESC LIMIT 12"""
            )
            top = list(cur.fetchall())

    print(f"\n结果：标签行 {n_tag} → {tag_total}（清理 {removed} 个）")
    print(f"     关联搬运 {moved} 条；comic_tag 行数 {n_ct} → {ct_total}")
    print("     （comic_tag 行数不变说明没有丢关联；减少的行数 = 合并时去掉的重复关联）")
    print("\n归一化后 TOP 标签：")
    for t in top:
        print(f"   {t['name']:<12} {t['comics']} 部")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
