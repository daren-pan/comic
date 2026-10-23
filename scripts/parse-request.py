#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""把《需求登记表》xlsx 解析成任务档案（00-request.md / 01-brief.md / state.json）。

用法
    python scripts/parse-request.py                      # 取 docs/requirements 里最新的 xlsx
    python scripts/parse-request.py <xlsx>               # 指定文件
    python scripts/parse-request.py <xlsx> --stdout      # 只打印 brief，不落盘
    python scripts/parse-request.py <xlsx> --id TASK-20261022-01
    python scripts/parse-request.py <xlsx> --out-dir /tmp/tasks
    python scripts/parse-request.py <xlsx> --force       # 覆盖已存在的任务目录

约定
    - 只认「需求单」sheet：**按固定行位取值**（第 4~17 行，B 列为填写内容），不依赖字段名匹配。
    - A 列字段名只用于：生成 00-request.md 的表格、以及模板版本校验（不符只告警，不阻断）。
    - 必填项缺失 → 打印清单并以 exit 2 退出，不生成任何文件。
    - 不修改源 xlsx；只读。
"""

import argparse
import csv
import datetime as dt
import json
import re
import sys
from pathlib import Path

try:
    import openpyxl
except ImportError:
    sys.exit(
        "缺少 openpyxl。安装：\n"
        r'  "C:/Users/caimf/.workbuddy/binaries/python/versions/3.13.12/python.exe" -m pip install openpyxl'
    )

ROOT = Path(__file__).resolve().parent.parent
SHEET_NAME = "需求单"

# (键, 字段名, 是否必填) —— 顺序即固定行位，见 ROW_MAP
FIELDS = [
    ("title", "任务标题", True),
    ("type", "需求类型", True),
    ("priority", "优先级", True),
    ("background", "背景与问题", True),
    ("goal", "目标·完成态", True),
    ("modules", "涉及模块", True),
    ("scope", "改动范围（白名单）", False),
    ("not_doing", "明确不做", False),
    ("db_change", "是否涉及数据库变更", True),
    ("acceptance", "验收标准", True),
    ("references", "参考材料", False),
    ("due", "期望完成时间", False),
    ("auto_commit", "允许自动提交", True),
    ("notes", "补充说明", False),
]

LABELS = {k: a for k, a, _ in FIELDS}

# 固定行位（模板 v1 起不变）：行号 → 字段键
ROW_MAP = [
    (4, "title"), (5, "type"), (6, "priority"), (7, "background"),
    (8, "goal"), (9, "modules"), (10, "scope"), (11, "not_doing"),
    (12, "db_change"), (13, "acceptance"), (14, "references"),
    (15, "due"), (16, "auto_commit"), (17, "notes"),
]

DB_ACTION = {
    "无": "无。运维阶段直接判 N/A，无需迁移与备份。",
    "表结构变更": "表结构变更（建表/加列/改列/删列/索引）。运维需先备份、执行 `tools/migrate.sh`、核对新结构。",
    "数据变更": "数据变更（迁移/回填/批量增删改）。运维需先 `mysqldump` + 数据目录快照，再执行，并留回滚点。",
    "两者都有": "结构与数据都要变。运维顺序：备份 → 改结构 → 迁数据 → 逐项验证。",
}


def norm(s) -> str:
    if s is None:
        return ""
    s = str(s)
    s = re.sub(r"\s+", "", s)
    return s.replace("（", "(").replace("）", ")")


def split_list(text: str):
    if not text:
        return []
    parts = re.split(r"[,，;；\n、]+", text)
    return [p.strip(" -·\t") for p in parts if p.strip(" -·\t")]


def split_steps(text: str):
    if not text:
        return []
    out = []
    for line in re.split(r"\r?\n", text):
        line = line.strip()
        if not line:
            continue
        line = re.sub(r"^(?:\d+\s*[.、)]|[-*•])\s*", "", line)
        if line:
            out.append(line)
    return out


def read_table(path: Path):
    """按固定行位取值（A 列字段名只用于表格展示与模板版本校验）。"""
    if path.suffix.lower() in (".csv", ".tsv"):
        return _read_csv(path)
    return _read_xlsx(path)


def _read_csv(path: Path):
    """CSV 模板：第 1 行表头，第 2~15 行依次是 14 个字段（A 字段名 / B 填写内容）。"""
    enc = "utf-8-sig"
    try:
        with path.open("r", encoding=enc, newline="") as f:
            rows = list(csv.reader(f))
    except UnicodeDecodeError:
        with path.open("r", encoding="gbk", newline="") as f:
            rows = list(csv.reader(f))

    body = rows
    if rows and rows[0] and norm(rows[0][0]) in ("字段", "序号", "项目"):
        body = rows[1:]

    raw, data, warns = [], {}, []
    for i, (key, label, _req) in enumerate(FIELDS):
        row = body[i] if i < len(body) else []
        a = row[0] if len(row) > 0 else ""
        b = row[1] if len(row) > 1 else ""
        val = str(b).strip()
        raw.append((str(a).strip() or label, val))
        data[key] = val
        if norm(a) != norm(label):
            warns.append(
                f"第 {i + 2} 行字段名读作「{a}」，模板预期「{label}」"
                f"——按位置仍取该行第 2 列，请确认模板版本"
            )
    return ["需求单"], raw, data, warns


def _read_xlsx(path: Path):
    wb = openpyxl.load_workbook(path, data_only=True)
    if SHEET_NAME not in wb.sheetnames:
        raise SystemExit(f"[ERROR] 找不到「{SHEET_NAME}」sheet，实际有：{wb.sheetnames}")

    ws = wb[SHEET_NAME]
    raw, data, warns = [], {}, []
    for r, key in ROW_MAP:
        a = ws.cell(r, 1).value
        b = ws.cell(r, 2).value
        val = "" if b is None else str(b).strip()
        raw.append((str(a).strip() if a is not None else f"(第{r}行)", val))
        data[key] = val
        expected = LABELS[key]
        if norm(a) != norm(expected):
            warns.append(f"第 {r} 行字段名读作「{a}」，模板预期「{expected}」——按位置仍取该行 B 列，请确认模板版本")
    return wb.sheetnames, raw, data, warns


def missing_required(data: dict):
    return [LABELS[k] for k, _a, req in FIELDS if req and not data.get(k)]


def pick_task_id(out_dir: Path, today: str) -> str:
    pat = re.compile(rf"^TASK-{today}-(\d+)$")
    used = []
    if out_dir.is_dir():
        for p in out_dir.iterdir():
            m = pat.match(p.name)
            if m:
                used.append(int(m.group(1)))
    return f"TASK-{today}-{(max(used) + 1) if used else 1:02d}"


def render_brief(task_id: str, data: dict, src: Path, now: dt.datetime) -> str:
    modules = split_list(data.get("modules", ""))
    scope = split_list(data.get("scope", ""))
    not_doing = split_list(data.get("not_doing", ""))
    steps = split_steps(data.get("acceptance", ""))
    refs = split_list(data.get("references", ""))
    db = data.get("db_change", "").strip() or "（未填）"
    db_line = DB_ACTION.get(db, f"{db}（未在已知选项内，运维需人工确认）")

    lines = [
        f"# {task_id} · {data['title']}",
        "",
        f"> 由 `scripts/parse-request.py` 从 `{src.name}` 自动解析，生成于 {now:%Y-%m-%d %H:%M}。",
        "> 本文件是**任务卡**；确认后即进入 设计 → 开发 → 测试 → 收尾。",
        "",
        f"**类型**：{data['type']}　|　**优先级**：{data['priority']}",
        "",
        "## 目标（完成态）",
        "",
        data["goal"] or "（未填）",
        "",
        "## 背景与问题",
        "",
        data["background"] or "（未填）",
        "",
        "## 影响模块",
        "",
    ]
    lines += [f"- {m}" for m in modules] or ["- （未填）"]
    lines += ["", "## 范围（白名单）", ""]
    if scope:
        lines += ["用户填写：", ""]
        lines += [f"- `{s}`" for s in scope]
        lines += ["", "若上面写的是模块名而不是具体文件，设计阶段会细化到文件级并回填本段。"]
    else:
        lines += [
            "（用户未指定具体文件）",
            "",
            "**由设计阶段按「影响模块」细化到文件级后回填本段**，测试按该清单核对 `git diff --name-only`。",
            "若设计发现需要动到上面未列出的模块 → **停下来找用户确认**，不得自行扩大。",
        ]
    lines += ["", "## 明确不做", ""]
    lines += [f"- {x}" for x in not_doing] or ["- （未声明）"]
    lines += [
        "",
        "## 数据库变更",
        "",
        f"**{db}** —— {db_line}",
        "",
        "## 验收标准",
        "",
    ]
    lines += [f"{i}. {s}" for i, s in enumerate(steps, 1)] or ["1. （未填）"]
    lines += ["", "## 参考材料", ""]
    lines += [f"- {r}" for r in refs] or ["- （无）"]
    lines += [
        "",
        "## 执行约定",
        "",
        f"- **提交策略**：{'允许自动提交（门禁通过即提交）' if data.get('auto_commit', '').startswith('是') else '不自动提交（改完等用户确认）'}",
        f"- **期望完成**：{data.get('due') or '未指定'}",
    ]
    if data.get("notes"):
        lines += ["", "## 补充说明", "", data["notes"]]
    lines += [
        "",
        "## 待确认（负责人提交用户拍板）",
        "",
        "- [ ] 范围白名单是否准确（有无漏掉的路径 / 多写的路径）",
        "- [ ] 验收标准是否都能用命令或可见结果判定",
        "- [ ] 是否现在开工（否则停在 brief 阶段等待）",
        "",
    ]
    return "\n".join(lines)


def render_request(task_id: str, data: dict, src: Path, raw, now: dt.datetime) -> str:
    lines = [
        f"# {task_id} · 原始需求",
        "",
        f"- 来源文件：`{src}`",
        f"- 解析时间：{now:%Y-%m-%d %H:%M}",
        "",
        "| 字段 | 填写内容 |",
        "| --- | --- |",
    ]
    for name, val in raw:
        cell = val.replace("\n", "<br>").replace("|", "\\|") if val else "（空）"
        lines.append(f"| {name} | {cell} |")
    lines.append("")
    return "\n".join(lines)


def main():
    ap = argparse.ArgumentParser(description="解析需求登记表 xlsx → 任务档案")
    ap.add_argument("xlsx", nargs="?", help="需求登记表路径；缺省取 docs/tasks/_inbox 里最新的 xlsx")
    ap.add_argument("--out-dir", default=str(ROOT / "docs" / "tasks"), help="任务档案根目录")
    ap.add_argument("--inbox-dir", default=str(ROOT / "docs" / "requirements"), help="缺省扫描目录（需求文档区）")
    ap.add_argument("--id", dest="task_id", help="指定任务 ID；缺省自动 TASK-YYYYMMDD-NN")
    ap.add_argument("--stdout", action="store_true", help="只打印 brief，不写文件")
    ap.add_argument("--force", action="store_true", help="任务目录已存在时覆盖")
    args = ap.parse_args()

    if args.xlsx:
        src = Path(args.xlsx).expanduser()
    else:
        inbox = Path(args.inbox_dir)
        cands = sorted(
            [p for p in inbox.glob("*.xlsx") if not p.name.startswith("~$")],
            key=lambda p: p.stat().st_mtime,
            reverse=True,
        ) if inbox.is_dir() else []
        if not cands:
            sys.exit(f"[ERROR] 没有找到需求表。把 xlsx 放到 {inbox} 再跑，或直接传路径参数。")
        src = cands[0]
        print(f"[info] 使用最新的需求表：{src}")

    if not src.is_file():
        sys.exit(f"[ERROR] 文件不存在：{src}")

    try:
        _sheets, raw, data, warns = read_table(src)
    except PermissionError:
        sys.exit(f"[ERROR] 读不了 `{src}` —— 文件正被 Excel/WPS 打开。关掉后重试。")
    except Exception as e:
        sys.exit(f"[ERROR] 解析失败：{type(e).__name__}: {e}")

    for w in warns:
        print(f"[warn] {w}")

    miss = missing_required(data)
    if miss:
        print("[ERROR] 以下必填项为空，请补全后重新回传：")
        for m in miss:
            print(f"  - {m}")
        sys.exit(2)

    now = dt.datetime.now()
    task_id = args.task_id or pick_task_id(Path(args.out_dir), now.strftime("%Y%m%d"))

    brief = render_brief(task_id, data, src, now)
    if args.stdout:
        print(brief)
        return

    task_dir = Path(args.out_dir) / task_id
    if task_dir.exists() and not args.force:
        sys.exit(f"[ERROR] 任务目录已存在：{task_dir}\n  换 --id，或加 --force 覆盖。")
    task_dir.mkdir(parents=True, exist_ok=True)

    (task_dir / "00-request.md").write_text(render_request(task_id, data, src, raw, now), encoding="utf-8")
    (task_dir / "01-brief.md").write_text(brief, encoding="utf-8")
    state = {
        "id": task_id,
        "stage": "brief",
        "gate": {"brief": "pending-user-confirm"},
        "attempt": 0,
        "source": src.name,
        "startedAt": now.isoformat(timespec="seconds"),
        "updatedAt": now.isoformat(timespec="seconds"),
    }
    (task_dir / "state.json").write_text(json.dumps(state, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    print(f"[OK] {task_id}")
    print(f"  00-request.md  {task_dir / '00-request.md'}")
    print(f"  01-brief.md    {task_dir / '01-brief.md'}")
    print(f"  state.json     {task_dir / 'state.json'}")
    print(f"  类型={data['type']} 优先级={data['priority']} 模块={','.join(split_list(data.get('modules',''))) or '-'} 数据库={data.get('db_change') or '-'}")
    print(f"  验收标准 {len(split_steps(data.get('acceptance','')))} 条，范围 {len(split_list(data.get('scope','')))} 条路径")


if __name__ == "__main__":
    main()
