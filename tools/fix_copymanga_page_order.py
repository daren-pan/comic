"""一次性数据修复：把 copymanga 章节的 `page.page_no` 重排成**页序**。

## 背景

copymanga 的章节接口 `results.chapter.contents[]` **顺序不保证是页序**（2026-10-07 实测：
某话 54 页里末尾 4 页的时间戳忽高忽低）。适配器此前直接按数组顺序编号 → 库里 `page_no`
就是乱序的，阅读器表现为「尾页跑到中间」。

- **新数据**：适配器已修（`sort_page_urls()` 按文件名首位数字升序编号，见
  `crawler-service/src/comic_crawler/sources/copymanga/adapter.py`），以后新登记的章节天然正确。
- **存量数据**：库内已登记的 `page_no` 仍是旧的乱序 → 本脚本负责重排。

## 怎么排

文件名形如 `{毫秒时间戳}{3 位序号}.jpg.c1500x.jpg` → **按首位数字升序即页序**
（线上那话前 50 页本就是升序，可确认这就是源站的页序口径）。
排序键直接复用适配器的 `sort_page_urls()` —— **不在这里复制一份**，避免两处规则漂移。

⚠️ 只处理「文件名都能取到数字且互不重复」的章节；取不到就**跳过并打印**，
绝不猜 —— 宁可留着旧顺序，也不要把本来正常的章节弄乱。

## 幂等 / 回滚

- **幂等**：重排后再跑，改动处数为 0（可重复运行）。
- **回滚**：`--apply` 会把「反向 UPDATE」写到 `backup/fix_copymanga_page_order_<时间戳>.sql`，
  需要时执行它即可还原（每行一条 `UPDATE page SET page_no=<旧值> WHERE id=<id>;`）。

## 用法（在 comic 仓库根目录）

    cd crawler-service
    # 先干跑，看看会改哪些章节（默认就是干跑，不写库）
    .venv/Scripts/python.exe ../tools/fix_copymanga_page_order.py
    # 确认无误再落库
    .venv/Scripts/python.exe ../tools/fix_copymanga_page_order.py --apply

连接参数用环境变量 `COMIC_MYSQL_*` 覆盖（默认兜底读仓库根 `deploy/.env`：宿主 `127.0.0.1:3309`）。
"""

from __future__ import annotations

import os
import re
import sys
from collections import defaultdict
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "comic-core" / "src"))
sys.path.insert(0, str(ROOT / "crawler-service" / "src"))

from comic_core.storage.mysql import MySQLStorage  # noqa: E402
from comic_crawler.sources.copymanga.adapter import sort_page_urls  # noqa: E402

#: 只认 copymanga —— 别的源的 contents 顺序是可靠的，不该被动
SOURCE = "copymanga"

_SQL_PAGES = """
SELECT c.id AS chapter_id, c.title AS chapter_title,
       cm.id AS comic_id, cm.title AS comic_title,
       p.id AS page_id, p.page_no, p.source_url
FROM page p
JOIN chapter c ON c.id = p.chapter_id
JOIN comic   cm ON cm.id = c.comic_id
WHERE cm.source = %s
ORDER BY c.id, p.page_no
"""


def _key_of(url: str) -> int | None:
    """文件名首位数字（与适配器同一口径）；取不到返回 None。"""
    m = re.match(r"(\d+)", url.rsplit("/", 1)[-1])
    return int(m.group(1)) if m else None


def _collect(store: MySQLStorage) -> dict[int, list[dict]]:
    with store._conn() as conn:
        with conn.cursor() as cur:
            cur.execute(_SQL_PAGES, (SOURCE,))
            rows = list(cur.fetchall())
    by_chapter: dict[int, list[dict]] = defaultdict(list)
    for r in rows:
        by_chapter[int(r["chapter_id"])].append(r)
    return by_chapter


def _plan(rows: list[dict]) -> tuple[list[tuple[int, int]], str]:
    """算出该章的新顺序。返回 (改动列表 [(page_id, 新 page_no)], 说明)。

    只返回**真的需要改**的行；排序键不可靠时返回空列表 + 原因。
    """
    urls = [str(r["source_url"]) for r in rows]
    keys = [_key_of(u) for u in urls]
    if any(k is None for k in keys):
        return [], "有文件名取不到数字 → 跳过（不猜）"
    if len(set(keys)) != len(keys):
        return [], "文件名数字有重复 → 跳过（不猜）"
    # 复用适配器同一把排序：它排 URL，这里按同样顺序给 page_no 重新编号
    ordered = sort_page_urls(urls)
    if ordered == urls:
        pass  # 顺序本来就对，也要重编号吗？—— 不需要：下面按位比对即可
    new_no = {u: i for i, u in enumerate(ordered, start=1)}
    changes: list[tuple[int, int]] = []
    for r in rows:
        want = new_no[str(r["source_url"])]
        if int(r["page_no"]) != want:
            changes.append((int(r["page_id"]), want))
    return changes, ""


def main() -> int:
    apply = "--apply" in sys.argv
    store = MySQLStorage()
    by_chapter = _collect(store)

    total_chapters = len(by_chapter)
    touched_chapters = 0
    touched_rows = 0
    skipped: list[str] = []
    reverse_sql: list[str] = []

    print(f"  库内 {SOURCE} 已登记页清单的章节: {total_chapters} 个"
          f"（{'落库模式 --apply' if apply else '干跑，不写库'}）")

    for chapter_id, rows in sorted(by_chapter.items()):
        if len(rows) < 2:
            continue
        changes, why = _plan(rows)
        head = f"    chapter {chapter_id} {rows[0]['chapter_title']}" \
               f"（{rows[0]['comic_title']}，{len(rows)} 页）"
        if why:
            skipped.append(f"{head.strip()} —— {why}")
            continue
        if not changes:
            continue
        touched_chapters += 1
        touched_rows += len(changes)
        print(f"{head}：{len(changes)} 处需要重排")
        for page_id, want in changes[:4]:
            old = next(int(r["page_no"]) for r in rows if int(r["page_id"]) == page_id)
            print(f"        page_id={page_id}  page_no {old} -> {want}")
        if len(changes) > 4:
            print(f"        …（共 {len(changes)} 处）")
        if apply:
            with store._conn() as conn:
                with conn.cursor() as cur:
                    for page_id, want in changes:
                        old = next(int(r["page_no"]) for r in rows if int(r["page_id"]) == page_id)
                        cur.execute("UPDATE page SET page_no = %s WHERE id = %s", (want, page_id))
                        reverse_sql.append(f"UPDATE page SET page_no = {old} WHERE id = {page_id};")

    print()
    print(f"  需要重排的章节: {touched_chapters} / {total_chapters}；涉及行数: {touched_rows}")
    for s in skipped:
        print(f"  跳过: {s}")

    if apply and reverse_sql:
        backup_dir = ROOT / "backup"
        backup_dir.mkdir(exist_ok=True)
        out = backup_dir / f"fix_copymanga_page_order_{datetime.now():%Y%m%d_%H%M%S}.sql"
        out.write_text(
            "-- 反向修复：把 copymanga 章节的 page_no 还原成执行前的值\n"
            + "\n".join(reverse_sql) + "\n",
            encoding="utf-8",
        )
        print(f"  已落库 ✓  回滚 SQL: {out.relative_to(ROOT)}")
    elif not apply and touched_rows:
        print("  干跑结束 —— 确认无误后加 --apply 落库")
    else:
        print("  无需改动 ✓（幂等：重排过再跑就是 0 处）")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
