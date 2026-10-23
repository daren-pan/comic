# TASK-20261022-01 测试报告 · 消息中心收藏漫画提示增加链接到详情页

> 测试：test（子 agent） ｜ 2026-10-22 ｜ 依据：`02-design.md` §9（9 条验收）
> 原则：**不引用 `03-impl.md` 的任何自测结论**，以下每条均为本次独立实跑。

## 0. 结论

**可交付**（1 项范围说明见 §2，不影响功能交付）。

- 两端 `detailPath` 判定、点击行为、跳转目标、已读语义、视觉区分全部符合设计。
- 静态门禁两端全绿；函数体双端逐字相同；零新增请求、零后端改动。
- 端到端行为验证**通过了 UI 链路**，但「真实账号登录」这一段因**无登录凭据**未能执行，用「注入合法结构 JWT + 拦截列表接口」的内存态替代（详见 §5.1，此为本次最大局限）。

## 1. 验证范围与命令

| # | 项目 | 命令 | 说明 |
|---|---|---|---|
| 1 | 范围门禁 | `git status --short` / `git diff --name-only` / `git ls-files --others --exclude-standard` | 见 §2 |
| 2 | web 静态 | `cd comic-web && npm run lint` / `typecheck` / `test` / `build` | 见 §3 |
| 3 | front 静态 | `cd comic-front && npm run lint` / `typecheck` / `test` / `build:h5` | 见 §3 |
| 4 | 逻辑矩阵 | 内联 `node` + `esbuild` 就地编译 `src/stores/message.ts` 后调用 `detailPath`（不落临时文件） | 见 §4 |
| 5 | 端到端 | Playwright（web :5173 / front :5174，后端 :8000） | 见 §6 |
| 6 | 数据核对 | `mcp__comic-mysql__execute_query`（只读） | `message` / `user` / `comic` |

## 2. 范围门禁（验收 9.0b）

`git diff --name-only` + 未跟踪文件：

| 文件 | 状态 | 归属 |
|---|---|---|
| `comic-web/src/stores/message.ts` | M | 白名单 #1 ✅ |
| `comic-web/src/views/MessagesView.vue` | M | 白名单 #2 ✅ |
| `comic-web/tests/message-detail-link.test.ts` | ?? 新增 | 白名单 #3 ✅ |
| `comic-front/src/stores/message.ts` | M | 白名单 #4 ✅ |
| `comic-front/src/pages/messages/index.vue` | M | 白名单 #5 ✅ |
| `comic-front/tests/message-detail-link.test.ts` | ?? 新增 | 白名单 #6 ✅ |
| `docs/tasks/` | ?? | 任务档案，允许（`01-brief.md` §范围已注明可含） |
| `scripts/README.md` | M | **白名单外** |
| `scripts/parse-request.py` | ?? | **白名单外** |
| `docs/requirements/` | ?? | **白名单外**（需求登记表 + README） |

**判定：功能改动恰好 6 个文件，无越界。**

后 3 项是「需求表 → 任务档案」流程工具的产物，与本功能无关：
- 时间戳 `scripts/README.md` 16:45、`scripts/parse-request.py` 17:18、`01-brief.md`（脚本生成）标注生成于 17:20，均**早于**开发改动（`comic-web/src/stores/message.ts` 17:51:09）；
- 内容上 `git diff scripts/README.md` 只有一行 `parse-request.py` 的用法表格，与消息页无关。

⚠️ 若负责人要求**字面**满足 9.0b（出现白名单外文件即失败），则本次需先由流程侧把这 3 项（`scripts/*`、`docs/requirements/`）单独提交或说明归属，再判范围通过。功能层面不受影响。

其余明确排除的文件**均未改动**（已核对）：两端 `types.ts`、`utils/router.ts`、`pages.json`、`components/Layout.vue`、`tests/conventions.test.ts`、任何后端文件。

## 3. 静态门禁（验收 9.0 前 3 条 + build）

### comic-web

| 命令 | 结果 | 判定 |
|---|---|---|
| `npm run lint`（`eslint src tests`） | 无输出，退出码 0（0 error / 0 warning） | 通过 |
| `npm run typecheck`（`tsc --noEmit`） | 无输出，退出码 0 | 通过 |
| `npm run test`（`vitest run`） | **5 files / 19 tests passed**：conventions 1、nav 4、season 2、usePagedList 6、**message-detail-link 6** | 通过 |
| `npm run build` | 见下「构建环境说明」 | 通过（换等价命令） |

### comic-front

| 命令 | 结果 | 判定 |
|---|---|---|
| `npm run lint` | 0 error，**4 warning**：全部在 `src/pages/reader/index.vue:72,73,77,81`（`no-explicit-any`）。该文件**不在本次 diff 中**，属改动前既有 | 通过（无新增告警） |
| `npm run typecheck` | 无输出，退出码 0 | 通过 |
| `npm run test` | **5 files / 25 tests passed**：conventions 1、season 2、usePagedList 6、router 10、**message-detail-link 6** | 通过 |
| `npm run build:h5` | 见下 | 通过（换等价命令） |

### 构建环境说明（重要，供复核）

`npm run build` / `npm run build:h5` 首次执行**失败**，错误与代码无关：

```
[safe-delete][SAFE_DELETE_BULK_CONFIRM_REQUIRED] {"count":53,"threshold":50,...,
 "targets":["D:\\RuoyiProject\\comic\\comic-web\\dist\\assets"]}
```

本机 agent 沙箱的 safe-delete shim 拦截了构建工具「清空 outDir」的批量删除（>50 项）。换成不删除 outDir 的等价命令后两端均成功：

| 端 | 命令 | 结果 |
|---|---|---|
| web | `npx vite build --emptyOutDir false` | `✓ built in 1.86s`（180 modules，退出码 0） |
| front | `npx uni build --emptyOutDir false` | `DONE Build complete.`（退出码 0） |

说明：这是**环境限制**，不是被测代码的问题；未改任何配置、未新增文件。构建产物 `dist/` 均为 gitignore，`git status` 未出现变化。

## 4. 逻辑验证（`detailPath` 三态）

方法：`node` 内联脚本 + `esbuild` 把 `src/stores/message.ts` 就地转成 CJS 后 `_compile`，**真实执行实现代码**（不是读代码推断），未落任何临时文件。

### 4.1 双端函数体一致性

去除 JSDoc 后按行比对：`FUNC_BODY_IDENTICAL = true`（front 版仅多一行「与 comic-web 保持一致」的注释，符合设计 §5.4）。

### 4.2 边界矩阵（web 版 19 格 / front 版 19 格，结果完全相同）

| # | 输入 | 期望 | web 实际 | front 实际 |
|---|---|---|---|---|
| 1 | `update` + `{comicId:12}` | `/comic/12` | `/comic/12` ✅ | `/comic/12` ✅ |
| 2 | `update` + `{comicId:'12'}`（字符串） | `/comic/12` | `/comic/12` ✅ | `/comic/12` ✅ |
| 3 | `update` + `{comicId:12,newChapters:3}` | `/comic/12` | `/comic/12` ✅ | `/comic/12` ✅ |
| 4 | `update` + `{comicId:0}` | `''` | `''` ✅ | `''` ✅ |
| 5 | `update` + `{comicId:-3}` | `''` | `''` ✅ | `''` ✅ |
| 6 | `update` + `{comicId:12.5}` | `''` | `''` ✅ | `''` ✅ |
| 7 | `update` + `{comicId:'abc'}` | `''` | `''` ✅ | `''` ✅ |
| 8 | `update` + `{comicId:null}` | `''` | `''` ✅ | `''` ✅ |
| 9 | `update` + `params:{}` | `''` | `''` ✅ | `''` ✅ |
| 10 | `update` + `params:null` | `''` | `''` ✅ | `''` ✅ |
| 11 | `update` + `params:[]` | `''` | `''` ✅ | `''` ✅ |
| 12 | `update` + `params:'str'`（非对象） | `''` | `''` ✅ | `''` ✅ |
| 13 | `sync` + `{comicId:12}` | `''` | `''` ✅ | `''` ✅ |
| 14 | `inspect` + `{comicId:12}` | `''` | `''` ✅ | `''` ✅ |
| 15 | `schedule` + `{comicId:12}` | `''` | `''` ✅ | `''` ✅ |
| 16 | `system` + `{comicId:12}` | `''` | `''` ✅ | `''` ✅ |
| 17 | `{comicId:' 12 '}`（带空格串） | 观察项 | `/comic/12` ⚠️ | `/comic/12` ⚠️ |
| 18 | `{comicId:true}` | 观察项 | `/comic/1` ⚠️ | `/comic/1` ⚠️ |
| 19 | `{comicId:[12]}` | 观察项 | `/comic/12` ⚠️ | `/comic/12` ⚠️ |

**判定：三态（可跳 / 不可跳 / 非 update）全部符合设计；无抛错。**

第 17~19 格是 `Number()` 强制转换的固有宽松面（`Number(true)=1`、`Number([12])=12`、`Number(' 12 ')=12`）。设计只要求「正整数即跳、非法退化为 `''`」，这三格不属于设计列举的非法值，且**真实数据不可能出现**（`fanout.py` 落的 `comicId` 是 int）。记为**观察项，不构成缺陷**，建议不做改动（收紧会偏离「字符串也认」的既有约定）。

## 5. 数据与账号现状

### 5.1 库内数据（只读，未做任何写操作）

| 查询 | 结果 |
|---|---|
| `SELECT ... FROM message WHERE kind='update'` | **3 条**：id 1/3/4，`comicId=44`，`to_user_id` = 10/10/4 |
| `SELECT id,title FROM comic WHERE id=44` | `标题，有用吗？`（status 连载中） |
| `SELECT kind,COUNT(*) FROM message GROUP BY kind` | update 3 / import 2 / sync 2 |
| `SELECT id,username,role FROM user` | 4 `caimf`(superadmin)、6 `test`(admin)、10 `xin`(user)、11 `111`(user) |
| `GET /api/messages`（无 token） | **401** —— 消息接口要登录 |

**关键限制：库内没有任何账号的明文口令**（项目约定「凭据不落盘」，`.workbuddy/memory/2026-09-22.md:417`），因此**无法用 `caimf`/`xin` 真实登录**。

### 5.2 采取的替代验证方式（不改库、不改代码）

1. 浏览器内写入**结构合法的 JWT**（`header.payload.sig`，payload 含未来 `exp`），使 `isLoggedIn()` 为真、门卫放行；
2. `page.route` 只拦截 `/api/messages*`，返回**与后端契约逐字段一致**的 feed（已核对 `api-service/services/messages.py:98-113` 的 `_to_contract`：`id:'msg-N'/messageId/kind/level/title/body/params/taskId/source/username/minRole/status/time/read`），并含三种条目：`update+comicId:44`、`sync（无 comicId）`、`update+params:{}`（老消息退化）；
3. 其余接口**真打后端**：`/api/comics/44`、页面路由、已读接口（已读请求也走 mock，仅为避免假 token 401）。

> 所有验证均在**浏览器会话内存**内构造，未写库、未改源码/测试/配置、未落临时文件。

## 6. 端到端验收（验收 A~E + 回归）

### 6.1 comic-web（:5173，390×844）

| 项 | 期望 | 实际 | 判定 |
|---|---|---|---|
| A-1 `linkable` 类 | update 且有 comicId → 含 `linkable` | `msg-item update done unread linkable` | 通过 |
| A-2 点击跳转 | `#/comic/44` | `#/comic/44` | 通过 |
| A-3 详情页标题 | `标题，有用吗？` | `.u-h1` = `标题，有用吗？` | 通过 |
| A-4 404 兜底 | 不出现「已下架」 | 未出现 | 通过 |
| A-5 已读请求 | 先 `POST /api/messages/4/read` | 依次发出 `POST /api/messages/4/read` → `POST /api/messages/read-all`（unmount） | 通过 |
| B-1 sync 无 `linkable` | 不含 | `msg-item sync done unread` | 通过 |
| B-2 点 sync 不跳 | hash 仍 `#/messages` | `#/messages` | 通过 |
| B-3 只标已读 | `unread` 消失 + `POST .../5/read` | 类变 `msg-item sync done`，请求已发 | 通过 |
| C 老 update（`params:{}`） | 无 `linkable`、点击不跳 | 类 `msg-item update done`，hash 仍 `#/messages` | 通过 |
| D 视觉区分 | 可点 `cursor:pointer`、不可点默认 | computed `cursor`：`pointer` / `auto` / `auto` | 通过 |
| E 未登录开 `#/messages` | 跳 `#/login?redirect=/messages` | `#/login?redirect=/messages`，密码框存在 | 通过 |
| F 未登录直接开 `#/comic/44` | 正常渲染、不跳登录 | `.u-h1` = `标题，有用吗？`，无密码框 | 通过 |
| G 顶栏按钮 | 「全部已读」「刷新」不跳转 | 两次点击后 hash 仍 `#/messages` | 通过 |
| H 375 窄屏 | 不横向溢出 | `scrollWidth 367 == clientWidth 367` | 通过 |
| I console | 无 error | 空 | 通过 |

### 6.2 comic-front（:5174，390×844）

| 项 | 期望 | 实际 | 判定 |
|---|---|---|---|
| D-1 `linkable` 类 | 同 web | `msg-item update done unread linkable` | 通过 |
| D-2 点击跳转（兼容层） | `#/pages/comic/index?id=44`（**不是** `#/comic/44`） | `#/pages/comic/index?id=44` | 通过 |
| D-3 详情页标题 | `标题，有用吗？` | `.u-h1` = `标题，有用吗？` | 通过 |
| D-4 路由兜底警告 | 无 `[router] 未登记的 web 路径` | 无任何 warn | 通过 |
| D-5 已读请求 | 先 `POST /api/messages/4/read` | 已发（+ unmount 时 `read-all`） | 通过 |
| D-6 触屏 `:active` | 样式存在（真机不阻塞） | `.msg-item.linkable:active { background: var(--primary-soft) }` 已在源码 | 通过（静态） |
| E-1 sync 无 `linkable` | 不含 | `msg-item sync done unread` | 通过 |
| E-2 点 sync 不跳 | hash 仍 `#/pages/messages/index` | 保持 | 通过 |
| E-3 只标已读 | `unread` 消失 | 类变 `msg-item sync done` | 通过 |
| E-4 老 update 不跳 | hash 不变 | 保持 | 通过 |
| F hover 视觉区分 | 可点标题变主题色 | `rgb(255,90,54)` vs 普通 `rgb(38,34,31)` | 通过 |
| G 顶栏按钮 | 「全部已读」「刷新」不跳 | 均保持 `#/pages/messages/index` | 通过 |
| H 390 窄屏 | 不溢出 | `scrollWidth 382 == clientWidth 382` | 通过 |
| I 未登录开消息页 | 跳登录 | `#/pages/login/index?redirect=%252Fmessages`，密码框存在 | 通过（双重编码为既有门卫行为，非本次改动） |

### 6.3 验收过程中发现的一处「看似失败」，实为测试环境副作用（留痕）

首次在 front 点击 update 条目后，hash 落到 `#/pages/login/index?redirect=%252F`。定位到 401 来源：

```
GET /api/users/<匿名UUID>/favorites/44  → 401
```

详情页会查「是否已收藏」，该请求带上了我注入的**假 token** → 后端判定无效 → `request.ts` 的 401 分支 `clearAuth()` 并跳登录。拦截该接口（返回 200 `{favorited:false}`）后，`bad401=[]`、hash 正确落到 `#/pages/comic/index?id=44`。web 端同理（首次也遇到过一次跳登录）。

**结论：这是「假 token」导致的鉴权副作用，不是被测代码的缺陷**；真实登录用户 token 有效时不会发生。

## 7. 回归（验收 9.6）

| 项 | 结果 | 判定 |
|---|---|---|
| 消息页「全部已读 / 刷新 / ← 返回」不触发跳转（两端） | 两端各点一次，hash 均不变 | 通过 |
| 顶栏铃铛角标 / 60s 轮询 | `Layout.vue` 未改动（不在 diff），本轮未单独压测 | 未验证（改动隔离，风险低） |
| 任务结果 toast 只弹不跳 | `Layout.vue` 未改动 | 未验证（同上） |
| 布局不溢出 375 / 390 | 已验证 | 通过 |
| front 详情页「← 返回」落 `/latest` | 详情页 H5 上**未找到可点的返回入口**（`getByText('返回')` count=0），未取到落点 | 未验证（R9 属既有全局规则，本次未改，不阻塞） |
| uni 原生端（App / 小程序） | 按 `01-brief.md`「明确不做」，仅验 H5 | 未验证（约定内） |

## 8. 缺陷列表

**无阻塞缺陷，无功能缺陷。**

| 级别 | 项 | 说明 |
|---|---|---|
| 观察 | `Number()` 归一偏宽 | `comicId: true / [12] / ' 12 '` 会被判为可跳（见 §4.2 第 17~19 格）。真实数据源（`comic_core.fanout`）只会写 int，不可触发；不建议改动 |
| 观察 | front 登录跳转 `redirect` 双重编码 | `?redirect=%252Fmessages`（web 是 `%2Fmessages`）。**既有行为**，不在本次 diff 内，不属本任务范围，仅供后续留意 |
| 环境 | 构建需 `--emptyOutDir false` | 沙箱 safe-delete 拦截 outDir 清空，非代码问题 |

## 9. 未验证项汇总（如实标注）

1. **真实账号登录的端到端**（最重要）：库内无口令，无法真实登录 `caimf`/`xin`，故「登录 → 服务端返回真实消息 → 点击跳转」这一整链**未端到端跑通**；已用「合法结构 JWT + 拦截列表接口（形状已与后端契约逐字段核对）+ 其余真打后端」替代，验证了 UI/路由/已读/退化分支。**建议负责人在有凭据时补一次真机验证（5 分钟）**。
2. 顶栏铃铛角标与 60s 轮询、任务结果 toast：改动隔离（`Layout.vue` 未改），未单独实测。
3. front 详情页「← 返回」落点：页面无可见返回入口，未取到。
4. uni 原生端（App/小程序）：任务卡明确不做。

## 10. 环境与清理

- 本次启动：`api`（:8000）、`front`（:5174）；`web`（:5173）为事先已在运行。
- 验证结束后已 `bash scripts/dev.sh down api front` 停止本人启动的服务，`web` 保持原状。
- 未修改任何源码 / 测试 / 配置；未 commit；未写库；未落临时文件。
