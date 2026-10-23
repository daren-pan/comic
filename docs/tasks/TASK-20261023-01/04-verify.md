# `TASK-20261023-01` 测试报告 · 收藏「新」角标 + 最近阅读点封面跳详情

## 1. 一句话结论

**`可交付`** —— 范围恰好 6 文件无越界；两端 lint/typecheck/vitest 全绿；判定矩阵 13 组合 × 双端全对（含「从未读过 → false」「updatedAt == readAt → false」）；两端 E2E 角标 / 点封面 → 详情 / 点续读 → 阅读器互不误触均实跑通过，0 缺陷。

---

## 2. 验证范围与命令

| 类别 | 做了什么 |
|---|---|
| 范围门禁 | `git status --short`、`git diff --name-only`；逐条比对 6 文件白名单，并追溯非本任务改动来源 |
| 静态门禁 | `comic-web`：`npm run lint` / `npm run typecheck` / `npx vitest run`；`comic-front`：同三条 |
| 逻辑验证 | `node --experimental-strip-types -e "…"` 内联直接 import 两端 `src/utils/favorite.ts`，跑 13 组输入（不落临时文件） |
| 端到端 | Playwright：`scripts/dev.sh up web`（:5173）+ `up front`（:5174），配 :8000 内存桩返回收藏/历史夹具；两端各验角标、点封面、点续读、收藏卡整卡 |

**服务状态**：验证前 api/web/front 全部未启动（`dev.sh status`）；验证后 `down web` / `down front` / 停 :8000 桩 → `dev.sh status` 三个端口均「未启动」，与验证前一致。

---

## 3. 范围门禁

| 检查 | 命令 | 结果 | 判定 |
|---|---|---|---|
| 改动文件 | `git status --short` | 本任务相关 6 个（2 M + 4 新） | 符合 |
| 白名单比对 | 人工逐条 | 全在：`comic-web/src/utils/favorite.ts`、`comic-web/src/views/MeView.vue`、`comic-web/tests/favorite.test.ts`、`comic-front/src/utils/favorite.ts`、`comic-front/src/pages/me/index.vue`、`comic-front/tests/favorite.test.ts` | 通过 |

**非本任务改动（已核实来源，不计越界）**：`comic-web/src/stores/message.ts`、`comic-web/src/views/MessagesView.vue`、`comic-front/src/stores/message.ts`、`comic-front/src/pages/messages/index.vue`、两处 `tests/message-detail-link.test.ts`（mtime 10-22 17:5x，属前序 `TASK-20261022-01` 未提交改动，与该任务白名单逐条吻合）；另有 `docs/requirements/`、`scripts/parse-request.py`、`.agent-shared|.workbuddy/skills/parse-requirement/`、两份 README（需求解析工具链，非源码）。

---

## 4. 静态门禁

| # | 命令 | 期望 | 实际 | 判定 |
|---|---|---|---|---|
| 1 | `cd comic-web && npm run lint` | 0 error | 0 error / 0 warning | ✅ |
| 2 | `cd comic-web && npm run typecheck` | 0 error | 0 error（tsc 无输出） | ✅ |
| 3 | `cd comic-web && npx vitest run` | 全过 | 6 files / **27 tests passed**（`favorite.test.ts` 8 tests） | ✅ |
| 4 | `cd comic-front && npm run lint` | 0 error | **0 error / 4 warning**（均在未改动的 `src/pages/reader/index.vue:72,73,77,81` 的 `no-explicit-any`，存量） | ✅ |
| 5 | `cd comic-front && npm run typecheck` | 0 error | 0 error | ✅ |
| 6 | `cd comic-front && npx vitest run` | 全过 | 6 files / **33 tests passed**（`favorite.test.ts` 8 tests） | ✅ |

---

## 5. 逻辑验证

> 直接 import 真实实现文件跑，不复用 `favorite.test.ts`；两端各跑 13 组。

| # | 输入（updatedAt / readAt） | 期望 | 实际（web / front） | 判定 |
|---|---|---|---|---|
| 1 | `2026-10-02T10:00Z` / `2026-10-01T10:00Z` | true | true / true | ✅ |
| 2 | `2026-10-01T10:00Z` / `2026-10-02T10:00Z` | false | false / false | ✅ |
| 3 | `2026-10-02T10:00Z` / 同一时刻 | false | false / false | ✅ |
| 4 | **readAt 缺失（id 不在 history 中，从未读过）** | false | false / false | ✅ |
| 5 | 空 history（收藏刚加入） | false | false / false | ✅ |
| 6 | `updatedAt` 缺失（`{}`） | false | false / false | ✅ |
| 7 | `updatedAt: ''` | false | false / false | ✅ |
| 8 | `updatedAt: 'not-a-date'` | false | false / false | ✅ |
| 9 | `updatedAt: null` | false | false / false | ✅ |
| 10 | `readAt: 'x'`（坏数据 → 无基准） | false | false / false | ✅ |
| 11 | 跨时区：`2026-10-02T08:00+08:00` / `2026-10-01T23:00Z` | true | true / true | ✅ |
| 12 | 同作品多条历史（各差 5 天）取最大后仍更晚 | true | true / true | ✅ |
| 13 | 多条历史中最新一条晚于更新 | false | false / false | ✅ |

**双端一致性**：`diff comic-web/src/utils/favorite.ts comic-front/src/utils/favorite.ts` 仅 1 行差异（互相指向的注释路径），**函数体逐字相同**；两份 `tests/favorite.test.ts` 差异仅 2 行注释。

---

## 6. 端到端验证

> 库内无「有更新」数据（见 §7），故用 :8000 内存桩按真实响应信封 `{code:0,message,data}` 提供夹具：
> A `id=901` 读于 10-01、10-20 更新（应亮）｜B `id=902` 读于 10-05、10-01 更新（不亮）｜C `id=903` **从未读过**、updatedAt 极晚（必须不亮）。
> 登录态用合法三段式 JWT（`exp` 未来）+ `comic_web_token` / `comic_web_user` 写入 localStorage；**未改库、未改源码**。

| # | 场景 | 步骤 | 期望 | 实际 | 判定 |
|---|---|---|---|---|---|
| 1 | web 角标三态 | `/#/me` → 「我的收藏」 | A 有「新」，B/C 无 | `[{A, badge:"新"},{B,null},{C,null}]` | ✅ |
| 2 | web 角标位置/穿透 | 读 computed style + `elementFromPoint` | 右上 6/6、`pointer-events:none` | `top:6 right:6 pe:"none"`；角标中心命中 `IMG.u-img` | ✅ |
| 3 | web 点角标区域不吞点击 | 鼠标点角标中心 | 跳收藏详情（回归） | `#/comic/901` | ✅ |
| 4 | web 最近阅读点封面 | 点第一行 `.row-cover` | 同标签页 `#/comic/<id>` | `#/comic/901` | ✅ |
| 5 | web 点续读不误触详情 | 点第一行「续读」 | 新标签 `#/reader/901/5001`，当前标签仍 `#/me` | 新标签 `#/reader/901/5001`；当前 `#/me` | ✅ |
| 6 | web 收藏整卡 | 点封面 → 详情 | `#/comic/901` | 同左 | ✅ |
| 7 | front 角标三态 | `/#/pages/me/index` → 「我的收藏」 | 同 #1 | `[{A,"新"},{B,null},{C,null}]`，位置 6/6、`pe:none` | ✅ |
| 8 | front 最近阅读点封面 | 点第一行 `.row-cover` | `pages/comic/index?id=901` | `#/pages/comic/index?id=901` | ✅ |
| 9 | front 点续读不误触 | 点「续读」 | 新标签 `pages/reader/index?comicId=901&chapterId=5001` | 同左；当前仍 `#/pages/me/index` | ✅ |
| 10 | front 收藏整卡 | 点收藏封面 | `pages/comic/index?id=901` | 同左 | ✅ |

**console**：两端均为 0 error（front 仅有 1 条「`/me` 无匹配路由」警告——因我用 web 路径初次进入，改用 uni 原生 `pages/me/index` 后正常，属操作路径而非缺陷）。

---

## 7. 未验证项及原因

| # | 未验证项 | 原因 | 建议 |
|---|---|---|---|
| 1 | **真实库数据**下角标（非桩） | 查 `favorite JOIN comic LEFT JOIN history`：全部记录 `sync_time <= read_at` 或 `read_at IS NULL`（如 user 4/comic 44 差 −9222s，user 10、11 无历史），**不存在「读后更新」样本**，且禁止写生产库 | 有一次真实「读后更新」后再肉眼确认 1 分钟；逻辑层已用 13 组矩阵兜住 |
| 2 | 真实登录凭据全链 | 库内无可用账号口令，改用合法结构 JWT + 桩 | 有凭据时补一次真机登录复核 |
| 3 | comic-front 小程序/App 原生端 | 仅起 H5（:5174）实跑 | 发版前在小程序端过一遍角标与点击分流 |

---

## 8. 缺陷清单

无。

---

## 备注

### 环境问题

- `comic-front` 的 `npm run lint` 有 4 条 `no-explicit-any` 警告，位于 `src/pages/reader/index.vue`（本任务未改动该文件，属存量），不影响判定。

### 替代验证方式

- 无「有更新」真实数据 + 无账号口令 → 用 `node - <<EOF` 起 :8000 内存桩（不落文件、不写库），经两端 vite `/api` 代理返回与后端同构信封；JWT 为合法三段式（`exp` 未来）。
- 逻辑矩阵用 `node --experimental-strip-types -e` 直接 import 两端 `favorite.ts`，未新建任何测试文件。

### 过程干扰（已排除）

- front 首次用 `#/me` 进入，页面空白 + Vue Router 警告「No match found for `/me`」：uni H5 用 `pages.json` 路由，改为 `#/pages/me/index` 后正常，非本次改动缺陷。
- Playwright 点 `.fav-badge` 报「img intercepts pointer events」：这正是 `pointer-events:none` 生效的证据（点击穿透到封面），随后用坐标点击验证 `#/comic/901` 跳转正常。
- 工作区另有 `TASK-20261022-01` 的未提交改动与需求解析工具文件，已核来源，未计入本任务范围。
