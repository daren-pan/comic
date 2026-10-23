# TASK-20261022-01 提测说明 · 消息中心收藏漫画提示增加链接到详情页

> 开发：dev（子 agent） ｜ 2026-10-22 ｜ 依据：`02-design.md`（已定稿）
> 状态：**已提测**（未 commit / 未 push；未启动 dev server、未跑 Playwright）

## 1. 改动清单（6 个文件，全部在白名单内）

| # | 文件 | 类型 | 改了什么 |
|---|---|---|---|
| 1 | `comic-web/src/stores/message.ts` | M | 在 `paramSummary` 之后新增导出纯函数 `detailPath(n: NoticeItem): string`：`kind === 'update'` 且 `Number(params.comicId)` 为正整数 → `/comic/<id>`，否则 `''`。判定唯一入口，页面不自己读 params |
| 2 | `comic-web/src/views/MessagesView.vue` | M | ① import 追加 `detailPath` + `import type { NoticeItem }`；② 新增 `openItem(n)`（先 `markRead` 不 await，再按 `detailPath` 非空才 `router.push`）；③ `:class` 追加 `linkable: !!detailPath(n)`；④ `@click` 改 `openItem(n)`；⑤ 样式加 `.msg-item.linkable { cursor: pointer }` 与 `.msg-item.linkable:hover .msg-summary`（仅类选择器） |
| 3 | `comic-web/tests/message-detail-link.test.ts` | ?? 新增 | `detailPath` 边界矩阵 6 个用例（见 §3） |
| 4 | `comic-front/src/stores/message.ts` | M | 与 #1 **函数体逐字相同**的 `detailPath`（`diff` 已比对通过），仅 JSDoc 多一行「与 comic-web 保持一致，改一处必须同步另一处」 |
| 5 | `comic-front/src/pages/messages/index.vue` | M | 同 #2 镜像改法；跳转走既有 `router.push`（`utils/router.ts` 兼容层 → `uni.navigateTo('pages/comic/index?id=')`，**未**直接调 `uni.navigateTo`、未动 `pages.json`）；样式在 `.msg-item.linkable` / `:hover` 之外**另加** `.msg-item.linkable:active { background: var(--primary-soft) }`（触屏无 hover，R8） |
| 6 | `comic-front/tests/message-detail-link.test.ts` | ?? 新增 | 与 #3 **同一份矩阵**，用例文件独立 |

**未改**（设计明确排除，实际也未碰）：两端 `types.ts`、`utils/router.ts`、`src/pages.json`、`components/Layout.vue`、`tests/conventions.test.ts`、任何后端文件。

## 2. 关键实现点（与设计逐条对齐）

- **判定规则**：只认 `kind === 'update'`，且 `comicId` 归一后是正整数；非法值（`0` / 负数 / 小数 / `'abc'` / `null` / `params` 为 null、非对象）→ `''`，不抛错、无 console 噪声。
- **点击顺序**：`markRead(n)` 先（**不 await**／front 用 `void`）→ 再 `detailPath` 非空才跳转；空则只标已读，走原行为。
- **整条可点**：热区仍是 `.msg-item` 本身，未新增第二个热区、未改布局、未加图标。
- **双端同口径**：两份 `detailPath` 函数体 `diff` 结果 `IDENTICAL`；两端返回值都是站内路径语义 `/comic/<id>`，由各端路由层翻译。
- **未做的项（按拍板）**：键盘可达性（`role`/`tabindex`/`@keyup.enter`）未做；`role` 未加，条目仍是 `div` / `view`。

## 3. 单测覆盖矩阵（两端文件相同）

| 输入 | 期望 |
|---|---|
| `kind:'update'`, `params:{comicId:12}` | `/comic/12` |
| `params:{comicId:'12'}` | `/comic/12` |
| `params:{comicId:12,newChapters:3,source:'baozimh'}`（多键） | `/comic/12` |
| `comicId: 0` / `-3` / `'abc'` / `null` / `12.5` | `''` |
| `params: null` / `{}` / `'not-an-object'` | `''` |
| `kind:'sync'/'inspect'/'system'` + `{comicId:12}` | `''` |

> 比设计矩阵多加了 `12.5` 与 `params:'not-an-object'` 两格（同一判定下的边界，不扩大实现范围）。

## 4. 自测（全部真跑，2026-10-22 17:54–17:55）

### comic-web

| 命令 | 结果 |
|---|---|
| `npx vitest run tests/message-detail-link.test.ts` | ✅ 1 file / **6 tests passed** |
| `npm run lint`（`eslint src tests`） | ✅ **0 error / 0 warning** |
| `npm run typecheck`（`tsc --noEmit`） | ✅ 无输出、退出码 0 |
| `npm run test`（全量） | ✅ **5 files / 19 tests passed**（既有 4 个文件 13 个用例 + 新增 6） |

### comic-front

| 命令 | 结果 |
|---|---|
| `npx vitest run tests/message-detail-link.test.ts` | ✅ 1 file / **6 tests passed** |
| `npm run lint` | ✅ **0 error**；4 warning 均为**改动前既有**的 `src/pages/reader/index.vue` 的 `no-explicit-any`（与我改的文件无关） |
| `npm run typecheck` | ✅ 无输出、退出码 0 |
| `npm run test`（全量） | ✅ **5 files / 25 tests passed** |

### 范围门禁

`git status --porcelain` 中属于本任务的变化**恰好 6 个文件**：
`M comic-front/src/pages/messages/index.vue`、`M comic-front/src/stores/message.ts`、
`M comic-web/src/stores/message.ts`、`M comic-web/src/views/MessagesView.vue`、
`?? comic-front/tests/message-detail-link.test.ts`、`?? comic-web/tests/message-detail-link.test.ts`。

> 同屏另有 `M scripts/README.md`、`?? docs/requirements/`、`?? docs/tasks/`、`?? scripts/parse-request.py` ——
> **开工前就已存在**（任务卡/设计流程产物），非本次改动。

## 5. 与设计的偏差

**无功能偏差。** 三处措辞级差异：

1. **`openItem` 的 `markRead` 写法**：web 直接 `msgStore.markRead(n)`；front 用 `void msgStore.markRead(n)`（`void` 只为显式表达"故意不 await"，CR 时可读性更好）。语义完全一致。
2. **`NoticeItem` 的 import 形式**：设计给了「随值 import 一行合并」或「另起 `import type`」两种，实际两处都统一用**独立的 `import type { NoticeItem }` 行**（双端同形）。
3. **`detailPath` 的 JSDoc**：front 版按 §5.4 要求多一行「与 comic-web 保持一致」提示；函数体逐字相同（已 `diff` 验证）。

## 6. 已知遗留 / 风险处理

| 项 | 处理情况 |
|---|---|
| **R10**（front vitest 是 node 环境，store import 链可能撞 `uni.*`） | **未触发**。实测 `import { detailPath } from '../src/stores/message'` 在 `environment: 'node'` 下可直接跑通（`storage`/`event`/`request` 的 `uni.*` 全在函数体内，与设计事实 #17 一致）。**未改** `vitest.config.ts`、未新增第 7 个文件 |
| **R8**（触屏无 hover） | 已按设计给 front 加 `.msg-item.linkable:active`（`--primary-soft` 底色）；未引入 uni `hover-class`。iOS 真机按压是否变色属呈现层非阻塞项 |
| **R9**（front 详情页「← 返回」落 `/latest`） | **未改**（既有全局层级规则，`utils/router.ts:158`）。从消息页进详情后返回不回消息页 —— 提测时请测试角色按「记录现状、不算失败」处理 |
| **R1/R2/R3**（作品下架 / 老消息缺 comicId / params 截断） | 均由 `detailPath` 返回 `''` 自动退化，两端详情页 404 兜底文案原样生效；未加任何探测请求 |
| 未覆盖 | 未做浏览器真机/Playwright 验证（属测试角色）；未跑 `npm run build` / `build:h5`（任务卡只要求 lint/typecheck/vitest） |
| 待办 | 按角色卡要求，改完源码需**重启 Vite**（`comic-web` :5173 / `comic-front` :5174 `dev:h5`）后测试角色再验 |
