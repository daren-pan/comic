---
name: 解析需求文档
description: >-
  当用户发来需求文档（xlsx）或说「解析需求 / 新需求 / 按这个需求做 / 需求文档给你了」时触发。
  负责把需求表同步到 docs/requirements/ 并解析成任务档案（00-request / 01-brief / state.json），
  然后汇报任务卡要点并询问是否开工。
when_to_use: >-
  命中任一即触发：
  (a) 用户发来 xlsx 需求文档（附件或 @ 引用）；
  (b) 「解析需求」「新需求」「按这个需求做」「需求文档给你了」；
  (c) 用户问「brief 出来了吗」「任务卡呢」。
---

# 解析需求文档

把《需求登记表》变成任务档案，走完工作流的第 0~1 步。

## 前置检查（先做，30 秒）

```bash
ROOT="$(git rev-parse --show-toplevel 2>/dev/null || pwd)"
[ -f "$ROOT/scripts/parse-request.py" ] && echo "READY: $ROOT" || echo "NOT_APPLICABLE"
```

- **`NOT_APPLICABLE`** → 当前项目没接入这套工作流。直接告诉用户「这个项目没有需求解析脚本（`scripts/parse-request.py`）」，然后**停止** —— 不要顺手创建整套流程文件。
- **`READY`** → 用 `$ROOT` 继续下面的步骤。

## 铁律（先看这五条）

1. **文件名必须英文** —— 目标路径一律 `docs/requirements/req-<YYYYMMDD>.xlsx`。
   ⚠️ 不要用 `需求登记表-*.xlsx` 这类名字：本机安全中心会对这类旧文件加逐文件规则，之后命令读不了（`Blocked by Security Center rules`）。
2. **必须显式传文件路径给脚本** —— 不要依赖"取最新"（会把 `req-template.xlsx` 空模板挑出来）。
3. **不自动开工** —— 生成 brief 后停下来问用户；除非用户说「直接开 / 不用确认」。
4. **不 commit** —— 解析只产出文档，提交由用户另行指令。
5. **同一个文件不重复解析** —— 先看 `docs/tasks/*/state.json` 的 `source` 是否已存在；已存在就提示用户，别生成第二份。

## 步骤

### 1. 定位源文件

优先用用户这一轮给的路径（附件 / @ 引用）。没有就用 `docs/requirements/` 里**最新的用户文件**（排除 `req-template.xlsx`）。

### 2. 同步到 `docs/requirements/`

```bash
mkdir -p "$ROOT/docs/requirements"
cp "<源文件>" "$ROOT/docs/requirements/req-$(date +%Y%m%d).xlsx"
```

**源文件不可读时**（报 `Permission denied` / `Blocked by Security Center rules`），这**不是脚本问题**。最常见原因是**文件名含中文**（本机安全规则对中文名的旧文件逐文件锁定）。停下来告诉用户：

> 这个文件我读不了（安全策略按文件名锁定了几类旧文件）。请把它**另存为英文名**（如 `req-20261023.xlsx`）
> 再发一次，或直接拖到 `docs/requirements/` 下。

**不要**反复重试同一路径，也不要尝试改系统设置绕过。

### 3. 解析

```bash
cd "$ROOT"
"C:/Users/caimf/.workbuddy/binaries/python/versions/3.13.12/python.exe" \
  scripts/parse-request.py "docs/requirements/req-<YYYYMMDD>.xlsx"
```

- 输出 `[OK] TASK-YYYYMMDD-NN` + 三个文件路径
- 报「以下必填项为空」→ **原样把清单转给用户**，让他补完再发；不要自己猜内容
- 报「任务目录已存在」→ 换 `--id`，不要用 `--force` 覆盖已完成的任务

### 4. 读 brief 并汇报

读 `docs/tasks/<TASK-ID>/01-brief.md`，向用户汇报（**≤10 行**）：

```
已解析 → TASK-<ID>
- 标题：<任务标题>
- 类型 / 优先级：<类型> / <优先级>
- 涉及模块：<模块>
- 数据库变更：<值>
- 验收：<条数> 条
- 状态：state.json = stage: brief，等你确认

要点：<1~2 行值得提醒的（如"范围只写了模块，设计阶段会细化"）>
```

然后问：**「开工吗？」**（记住：不要自己开工）

## 失败处置

| 现象 | 处理 |
|---|---|
| `Permission denied` / `Blocked by Security Center rules` | 文件被锁（多为**中文名**）→ 请用户另存英文名再试 |
| `没有找到需求表` | 目录里没有 xlsx → 请用户投放 |
| `以下必填项为空` | 原样转告用户，不补写 |
| 文件名含中文且读不了 | 改成英文名重试一次；仍不行就请用户另存 |
| `NOT_APPLICABLE` | 本项目未接入 → 告知并停止 |

## 产出物

| 文件 | 说明 |
|---|---|
| `docs/requirements/req-<日期>.xlsx` | 需求表副本（英文名，可反复读） |
| `docs/tasks/<ID>/00-request.md` | 表格原文留档 |
| `docs/tasks/<ID>/01-brief.md` | 任务卡（结构固定，见 `_template/01-brief.md`） |
| `docs/tasks/<ID>/state.json` | `stage: brief`，等确认 |

## 依赖（缺了就无法工作）

| 依赖 | 缺失时 |
|---|---|
| `scripts/parse-request.py` | 判 `NOT_APPLICABLE`，停止 |
| `docs/tasks/_template/req-template.xlsx` | 提示用户「模板不在，先跑 `make_req_template.py` 生成」 |
| `docs/tasks/_template/01-brief.md` | 不影响解析（brief 由脚本渲染），仅影响模板对照 |
