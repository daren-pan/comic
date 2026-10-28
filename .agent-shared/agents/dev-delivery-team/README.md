# 通用研发交付团队（dev-delivery-team）

一个不绑定具体项目的软件研发交付团队：需求 → 架构分层 → 全栈实现 → 独立验收 → 技术评审 → 发布与文档，**五个角色，每个角色的写权限都被明确限定**。

## 类型

Team 型（多角色协作团队，1 主理人 + 5 成员）

## 编制

| 组 | Agent ID | 花名 · 职业 | 职责 | 权限档 |
|---|---|---|---|---|
| 决策 | `product-manager` | 许清楚 · 产品经理 | 需求澄清、范围界定、可判定验收标准 | 只读 `mode: "plan"` |
| 决策 | `architect` | 高见远 · 架构与评审 | 项目画像、分层与依赖、接口契约、文件白名单；实现后做技术评审 | 只读 `mode: "plan"` |
| 实现 | `dev` | 谷可全 · 全栈工程师 | 界面规格 + 前端 + 后端 + 自测 | 可写，限白名单 |
| 保障 | `qa-verifier` | 严过关 · 质量工程师 | 独立重跑、真浏览器 / 真接口取证、单一结论 | 只写报告 |
| 保障 | `release-ops` | 邵可稳 · 发布与文档 | 发布步骤、回滚、观测点、文档沉淀 | 只写报告与文档 |

主理人：`dev-delivery-team-lead`（齐活林 · 交付总监）—— 唯一对用户开口，负责编排、门禁与权限核对。

> `architect` 在两处出场：Phase 2 出方案、Phase 5 做评审。**两次必须分开 spawn**，否则会自评放水。

## 权限设计

平台不允许在 Agent 定义里声明工具白名单，所以权限落在三处：

1. **spawn `mode`**：只读档一律 `mode: "plan"`，从机制上挡住写操作
2. **文件级白名单**：架构师出 `路径:行号`，实现组只许改这些
3. **事后 diff 核对**：主理人跑 `git diff --name-only` 逐条比对，越界即打回

| 档位 | 成员 | 可写范围 |
|---|---|---|
| 只读档 | 产品经理 / 架构与评审 | 只写自己那份阶段文档 |
| 可写档 | 全栈工程师 | 白名单内文件 + `03-dev.md` |
| 产物档 | 质量工程师 / 发布与文档 | 只写报告、文档、证据 |

**凭据读取禁令**：成员不得读取 `.env` / `*.secret` / `secrets/`，需要数据只能走项目提供的受限入口或回报主理人。「读」这个动作本身就算越界。

数据库账号分权（迁移账号 / 只读账号 / 应用账号）**暂缓落地**，当前只有角色边界与凭据禁令生效。

## 工作流（7 阶段）

```
Phase 0 接单 + 项目画像（主理人 + architect）
Phase 1 需求            product-manager
Phase 2 架构分层        architect（白名单 + 接口契约 + 风险）
Phase 3 实现            dev（界面规格 → 后端 → 前端 → 联调自测）
Phase 4 独立验收        qa-verifier
Phase 5 技术评审        architect（重新 spawn，只对 diff）
Phase 6 发布 + 文档     release-ops
Phase 7 收尾            主理人
```

按任务类型裁剪：纯后端跳过界面规格、纯前端跳过接口部分、只出方案不 spawn `dev`、只验收走 0→4→5。

## 产物目录

```
docs/delivery/
├── _profile/PROJECT-PROFILE.md   # 项目画像（跨任务复用）
├── _profile/LAYER-MAP.md         # 分层归属表
└── <YYYYMMDD>-<slug>/
    ├── 00-task.md ~ 07-close.md
    └── docs/ · evidence/
```

每份报告都用统一的头尾：头部是「任务 / 阶段 / 作者 / 上游输入 / **状态**（完成·有条件完成·阻塞）」，末尾是「移交（交给谁 / 需拍板 / 未做未验证）」，中间才是各角色的固定章节。详见主理人 §五。

## 使用示例

- 先读一遍这个项目，出项目画像和分层归属表
- 这个需求从产品、架构到全栈实现，走完整流程
- 只做后端改动，跳过界面

## 修改指南

| 想改什么 | 改哪里 |
|---|---|
| 某角色的职责 / 边界 | `agents/<id>.md` 正文 |
| 阶段的先后与门禁 | `agents/dev-delivery-team-lead.md` 的 §三、§四 |
| 权限档位划分 | 主理人 §二 + 各成员「权限边界」章节 |
| 报告的统一格式 | 主理人 §五「报告统一骨架」 |
| 展示信息（名字 / 描述 / 标签） | `.codebuddy-plugin/plugin.json` |
| 新增角色 | 新建 `agents/<new-id>.md` + 同步 `plugin.json` 的 `agents` / `teamInfo.memberAgents` / `members` |

改完必须重跑校验与注册，否则不生效。

## 头像

在 `avatars/` 下，命名与 `plugin.json` 的 `avatar` 字段一致。自定义要求：PNG/JPG、512×512、单张 ≤500KB。**当前尚未生成。**

## 校验与注册

```bash
python scripts/validate_expert.py <expert-dir>
python scripts/register_expert.py <expert-dir>
```

## 打包分享

```bash
python scripts/package_expert.py <expert-dir> [output-dir]
```
