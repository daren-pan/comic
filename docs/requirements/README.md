# requirements —— 需求文档区

**你（用户）投放需求表的地方。**

## 怎么用（三步）

1. 打开模板 `req-template.xlsx`（本目录），另存为任意**英文名**（如 `req-20261023.xlsx`）
2. 按「需求单」页填写，**关掉 Excel** 后说一声「**解析需求**」
3. 我生成任务卡 → 你确认 → 开跑

> 技能名：`解析需求文档`（触发词：解析需求 / 新需求 / 按这个需求做）。
> **命名不用你操心**：我复制进本目录时会自动加唯一序号（`req-<日期>-01.xlsx`、`-02`…），同名多次发送也不会覆盖。

## 文件名为什么必须用英文

本机安全中心会给**特定旧文件**加逐文件规则，之后命令读不了它（报 `Blocked by Security Center rules`）。
实测：`需求登记表-v1.xlsx` 这类中文旧名会被锁，而 `req-20261023.xlsx`、`req-template.xlsx` 完全正常。

所以约定：**模板 `req-template.xlsx`，填写后存成英文名**；落库存档一律 `req-<YYYYMMDD>-<NN>.xlsx`（**序号唯一，永不覆盖历史存档**）。
你直接从桌面把文件发给我也行 —— 我负责复制和编号。

## 解析方式：按固定行位

读「需求单」sheet 第 **4~17 行**的 **B 列**，不依赖字段名匹配（A 列只用于留档与版本校验，对不上只告警）。

| 行 | 字段 | | 行 | 字段 |
|---|---|---|---|---|
| 4 | 任务标题 | | 11 | 明确不做 |
| 5 | 需求类型 | | 12 | 是否涉及数据库变更 |
| 6 | 优先级 | | 13 | 验收标准 |
| 7 | 背景与问题 | | 14 | 参考材料 |
| 8 | 目标·完成态 | | 15 | 期望完成时间 |
| 9 | 涉及模块 | | 16 | 允许自动提交 |
| 10 | 改动范围（白名单） | | 17 | 补充说明 |

**「改动范围」是选填** —— 记不住文件名就留空，设计阶段会按模块细化后回填。
**「涉及模块」必填** —— 只选模块即可，不用写文件名。

## 产出

`docs/tasks/<TASK-ID>/`：

| 文件 | 内容 |
|---|---|
| `00-request.md` | 表格原文留档 |
| `01-brief.md` | 任务卡：目标 / 范围 / 不做 / 数据库变更 / 验收标准 |
| `state.json` | 阶段状态（初始 `stage: brief`，等确认） |

## 脚本

```bash
python scripts/parse-request.py docs/requirements/req-20261023.xlsx
python scripts/parse-request.py <文件> --stdout     # 只看 brief，不落盘
python scripts/parse-request.py <文件> --id TASK-xxx # 指定任务号
```

支持 `.xlsx` 与 `.csv`。

## 模板维护

改字段改 `docs/tasks/_template/make_req_template.py`，然后：

```bash
python docs/tasks/_template/make_req_template.py
```

会把新模板写到 `docs/tasks/_template/req-template.xlsx`，复制一份到本目录即可。

## 目录约定

- `docs/requirements/` —— **需求输入**（你放的原始文档）
- `docs/tasks/<TASK-ID>/` —— **任务档案**（00~06 + state.json）
- `docs/tasks/_template/` —— **模板**（7 份阶段文档 + 需求表 + 生成脚本）
