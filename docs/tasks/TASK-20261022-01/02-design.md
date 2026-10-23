# TASK-20261022-01 设计 · 消息中心收藏漫画提示增加链接到详情页

> 设计：design（子 agent） ｜ 2026-10-22 ｜ 上游任务卡：`01-brief.md`
> 本次**只出方案**，不写实现、不跑构建 / 测试。

## 0. 一句话结论

后端**已**在收藏更新消息里带了 `params.comicId`（`comic-core/src/comic_core/fanout.py:103-107`），
缺的只是前端「把它当链接用」这一步 —— 改动收敛在**每端各 2 个源码文件**（comic-web + comic-front 双端同步，各 2 个，+2 个可选单测文件），
**无接口 / 无表结构 / 无依赖变更 / 零新增请求**。
> 2026-10-22 用户已拍板（见 §1.1）：双端同步、整条可点击、本次不补键盘可达性。

## 1. 目标与非目标

### 目标（完成态）

1. 消息中心里 `kind === 'update'` 且 `params.comicId` 有效的条目**可点击跳转**到该作品详情页（web `/#/comic/<comicId>`；front `#/pages/comic/index?id=<comicId>`，由 `utils/router.ts` 翻译 —— 两端同一个入口 `router.push('/comic/<id>')`）。
2. 跳转前后**不改变**已有的已读语义：点过的那条照旧 `markRead`，离开页面照旧 `markAllRead`。
3. 其它类型（任务消息 `sync` / `inspect` / `schedule` / `system`…）、以及 `params.comicId` 缺失的条目**行为完全不变**（点击只标已读）。
4. 可点击与不可点击的条目在**视觉上可区分**（cursor + hover 反馈；移动端另加 `:active` 按压反馈，见 §5.5），不新增图标 / 不改布局。
5. **双端同口径**：comic-web（:5173）与 comic-front（:5174）行为一致 —— 同一份 `detailPath` 判定、同一条跳转目标语义，只是路由机制不同（`router.push` vs `uni.navigateTo`）。

### 非目标（明确不做）

- **不改数据库**：不给 `message` 加 `comic_id` 列（params 已有，且加列要迁移 + 回填，收益为零）。
- **不改后端**：不动 `api-service/services/messages.py`、`routers/messages.py`、`comic_core.fanout`、`message` 表 DDL。
- **不改 `/api/messages` 出参契约**：前端从既有 `params` 里读，不新增 `comicId` 顶层字段。
- **不动顶栏任务 toast**（`comic-web/src/components/Layout.vue:316-323`）：它是「任务结果提示」，不是收藏更新入口。
- **不改消息页的已读时机**（进页不标、离开标全部）——那是刻意的设计，见 `MessagesView.vue:36-40` 注释。
- **不引入 `router-link` / `<a>`**：本项目全站站内跳转惯例是 `router.push()`（`HomeView.vue:66`、`me/index.vue:86` 等同形），不新增第二种写法。
- 不做「点击区域以外的手势 / 长按菜单 / 二次确认」。
- ~~本次不改 comic-front~~ → **已改为同步修改**（用户 2026-10-22 拍板，见 §1.1 / §7）。
- **不做 uni 原生端（App / 小程序）专门验证**：comic-front 只按 H5 形态（`npm run dev:h5`，:5174）验收；`uni.navigateTo` 在其它端语义相同，但本次不测。
- **不改 comic-front 的层级返回规则**：从消息页进详情后，详情页「← 返回」仍按既有写死层级回 `/latest`（`utils/router.ts:158`），不回消息页 —— 这是 2026-10-09 用户指定的既有行为，属独立需求（见 §6.2 R9）。

### 1.1 已确认决策（2026-10-22 用户拍板，三项全按推荐）

| # | 决策点 | 结论 |
|---|---|---|
| ① | 是否同步 comic-front | **同步做**。两端功能等价是项目硬约定（`AGENTS.md:19-20,34-35`），只改一端 = 需求只完成一半 |
| ② | 点击区域 | **整条消息可点**（不新增第二个热区，移动端 375px 下最省事、最好点） |
| ③ | 键盘可达性 | **本次不做**（本页所有条目原本都不可键盘聚焦，补 `role`/`tabindex`/焦点样式属独立可访问性需求） |

## 2. 事实核对（设计前独立复核过，均以当前代码为准）

| # | 事实 | 取证位置 |
|---|---|---|
| 1 | `message` 表**没有** comic_id 列；与作品相关的信息只在 `params JSON` 里 | `comic-core/sql/mysql_schema.sql:238-271`（列：kind/level/title/body/params/task_id/source/user_id/username/to_user_id/min_role/created_at） |
| 2 | 收藏更新消息的 `params` 里有 `comicId`（int）、`newChapters`、`source`；`KIND = "update"` | `comic-core/src/comic_core/fanout.py:45`、`:99-111` |
| 3 | `params` 落库前被 `json.dumps(...)[:2000]` 截断；`comicId` 是**第一个键**，不受影响 | `comic-core/src/comic_core/storage/mysql/message_store.py:214-220` |
| 4 | 出参把 `params` 反序列化成对象（失败给 `None`）→ 前端拿到的是 `Record<string,unknown> \| null` | `api-service/services/messages.py:86-99`、`:113` |
| 5 | 前端类型 `MessageItem` 已含 `params` 与 `kind`，**无需改类型定义** | `comic-web/src/types.ts:313-334`（`params:318`… 具体 `:326`；`kind:316`） |
| 6 | 消息条目**只有一处渲染**：`MessagesView.vue` 的 `v-for` | `comic-web/src/views/MessagesView.vue:66-88`（点击在 `:72`）；全量 grep 确认 Layout 只渲染 toast |
| 7 | 详情页路由为 `/comic/:id`（hash 模式），参数取 `route.params.id` | `comic-web/src/router.ts:4`（`createWebHashHistory`）、`:66`；`ComicDetailView.vue:87` |
| 8 | 详情页**不要求登录**即可看；404 已有「已下架或不存在」兜底文案 | `ComicDetailView.vue:55-66`、`:93`（仅收藏/评论要登录） |
| 9 | `update` 类消息的唯一生产方是 `fanout.build_payloads`（`grep '"update"'` 只命中它） | 见上 #2 |
| 10 | `paramSummary()` 对 `update` 类**返回空串**（它只处理 `since/until/mode/limit/keyword/firstChapters`），所以加链接不会和「入参」那行打架 | `comic-web/src/stores/message.ts:80-100`（`hasWindow` 只含 sync/inspect/schedule） |
| 11 | **comic-front 有同构的 store**，`NoticeItem`/`paramSummary`/`kindLabel` 与 web 版逐字相同，可直接镜像 `detailPath` | `comic-front/src/stores/message.ts:26`（类型）、`:80-100`（`paramSummary`）、`:102`（`defineStore`） |
| 12 | comic-front 消息页与 web 版逐行同构：**点击在 `:80`**，`class` 绑定在 `:79`，样式块止于 `:182` | `comic-front/src/pages/messages/index.vue:74-96`、`:119-126`、`:173-182` |
| 13 | comic-front **不需要新写跳转**：页面已 `import { setRoute, useRouter }`，`router` 在 `:21` 就绪；兼容层把 `/comic/<id>` 解析成 `pages/comic/index?id=<id>` | `pages/messages/index.vue:18,21`；`utils/router.ts:93-94`（`/^\/comic\/(\d+)$/` 分支）、`:111-127`（`go()` → `uni.navigateTo`） |
| 14 | 详情页取参用 uni 惯例 `onLoad(options)` 的 **`options.id`**（不是 `comicId`），且 `pages/comic/index` 已在 `pages.json` 注册 | `comic-front/src/pages/comic/index.vue:86-90`（`comicId = Number(options?.id ?? 0)`）；`src/pages.json:7` |
| 15 | comic-front 详情页 404 也有「作品不存在或已下架」兜底；未登录可看详情（只收藏/评论要登录） | `pages/comic/index.vue:23-24,63-65,222-223`、`:93-97`（收藏前查登录） |
| 16 | comic-front 有 vitest（`environment: 'node'`，`include: tests/**/*.test.ts`）与 4 个纯函数用例；**没有** `@vue/test-utils` | `comic-front/vitest.config.ts:12-17`、`comic-front/package.json`（devDependencies）、`comic-front/tests/`（4 个文件） |
| 17 | `stores/message.ts` 的 import 链（`../api` → `request/auth` → `utils/storage,event`）**模块级无 `uni.*` 调用**（全在函数体内），因此 node 环境下可被单测 import | `src/api/request.ts`、`src/api/auth.ts`、`src/utils/storage.ts`、`src/utils/event.ts`（已逐个核对顶层语句） |

## 3. 方案

### 3.1 判定规则（唯一真源，纯函数）

```
detailPath(n) = n.kind === 'update' && Number.isInteger(Number(n.params?.comicId)) && > 0
              ? `/comic/${Number(n.params.comicId)}`
              : ''
```

要点：
- **只认 `kind === 'update'`**：任务消息的 `params` 不保证有 `comicId`，不允许「有 comicId 就跳」这种隐式规则（将来别的类型带同名字段会被误连）。
- `Number()` 兜一层：老消息 / 外部写者可能把它写成字符串 `"12"`。
- 非法值（缺失 / `null` / `0` / 负数 / `"abc"` / `params` 为 null 或数组）→ 返回 `''`，**退回原行为**，不抛错、不 console 噪声。
- 放在 `stores/message.ts` 而不是组件里：与 `paramSummary` 同类（展示期归一），**且能脱离组件被 vitest 直接测**（本项目没装 `@vue/test-utils`，写在组件里就等于放弃单测覆盖）。
- **双端函数体逐字相同**（两份 `stores/message.ts` 本来就是同构的，各留一份、不抽公共包 —— 两个前端没有共享代码的通道，`AGENTS.md` 也没有跨前端依赖的约定）：返回值都是**站内路径语义** `/comic/<id>`，由各端的路由层分别翻译（web → `router.push`；front → `router.push` 经 `utils/router.ts` 兼容层 → `uni.navigateTo('pages/comic/index?id=')`）。

### 3.2 交互

- 整条 `.msg-item` 仍是唯一热区（**不新增第二个热区**）：`@click="openItem(n)"`。
- `openItem(n)` 顺序：**先 `msgStore.markRead(n)`（不 await，保持原有的乐观更新），再在 `detailPath` 有值时 `router.push(path)`**。
  - 不 await 的理由：`markRead` 失败只影响未读角标（store 里已 catch），不该拖住跳转；而离开页面时 `onBeforeUnmount → markAllRead()` 会整体落库，不存在漏标。
- 可点击条目加 `linkable` 类：`cursor: pointer` + hover 时标题变主题色并下划线，作为「这条能点」的提示。**不加箭头图标**（会改动 `.msg-item-head` 布局，且移动端 375px 宽容易挤）。
- 不可点击条目保持现状（默认光标，无 hover 反馈）。

### 3.3 数据流（一次点击）

```
点击 .msg-item
  ├─ msgStore.markRead(n)  → POST（message_read 记账），item.read = true，unread--
  └─ detailPath(n)
        ├─ ''      → 什么都不做（任务消息 / 老消息）
        └─ '/comic/12' → router.push → ComicDetailView(route.params.id=12)
                                        └─ 404 → gone 文案（作品已下架，不白屏）
```

comic-front 同一动作的落地（**唯一差异是最后一步的翻译层**）：

```
点击 .msg-item（uni `<view @click>`）
  ├─ msgStore.markRead(n)          —— 与 web 同一份 store 实现
  └─ detailPath(n) === '/comic/12'
        └─ router.push('/comic/12')            ← utils/router.ts 兼容层（页面已 import，无需新增）
             └─ toUniUrl() 命中 /^\/comic\/(\d+)$/ → '/pages/comic/index?id=12'
                  └─ uni.navigateTo(...)        ← 压栈（消息页保留在栈内）
                       └─ pages/comic/index.vue onLoad: comicId = Number(options.id) = 12
                            └─ 404 → gone「作品不存在或已下架」（:222-223）
```

## 4. 文件级白名单

> 用户填写范围 = 模块 `comic-web`（模块级），**2026-10-22 已追加确认同步 `comic-front`**。
> 本节是设计细化（已同步回填 `01-brief.md`）。共 **6 个文件**：4 个源码 + 2 个新增测试（测试角色写）。
> **跨模块**：`comic-web` + `comic-front` —— **已获用户确认**（§1.1-①），不再是「未经确认的扩大」。

| # | 文件（相对仓库根） | 模块 | 角色 | 改什么 | 必需 |
|---|---|---|---|---|---|
| 1 | `comic-web/src/stores/message.ts` | comic-web | 源码 | 新增导出纯函数 `detailPath(n: NoticeItem): string` | 是 |
| 2 | `comic-web/src/views/MessagesView.vue` | comic-web | 源码 | 点击改走 `openItem()`；`linkable` 类与 hover 样式 | 是 |
| 3 | `comic-web/tests/message-detail-link.test.ts` | comic-web | **新增**（测试角色写） | `detailPath` 的边界用例 | 否（推荐） |
| 4 | `comic-front/src/stores/message.ts` | comic-front | 源码 | 与 #1 **逐字相同**的 `detailPath` | 是 |
| 5 | `comic-front/src/pages/messages/index.vue` | comic-front | 源码 | 点击改走 `openItem()`；`linkable` 类 + `:hover` / `:active` 样式 | 是 |
| 6 | `comic-front/tests/message-detail-link.test.ts` | comic-front | **新增**（测试角色写） | 同 #3 的矩阵（用例文件独立，不共享） | 否（推荐） |

**白名单外一律不动**：
- web 侧：`types.ts`（类型已够用）、`api/*`、`router.ts`（`/comic/:id` 路由已存在）、`components/Layout.vue`（toast 不动）、`tests/conventions.test.ts`。
- front 侧：`types.ts`（`MessageItem` 已含 `params`/`kind`，`comic-front/src/types.ts:313-334`）、`utils/router.ts`（`/comic/<id>` 分支已在 `:93-94`，**不需要登记新路径**）、`src/pages.json`（`pages/comic/index` 已注册 `:7`）、`api/*`、`components/Layout.vue`（顶栏 toast 不动）、`tests/conventions.test.ts`。
- 两端后端一律不动。

## 5. 改动清单（`路径:行号` → 改成什么）

### 5.1 `comic-web/src/stores/message.ts`（在 `:100` 之后、`:102` `defineStore` 之前插入）

- **`:100` 之后新增**（紧邻 `paramSummary`，同一类"展示期归一"工具）：

```ts
/**
 * 消息条目的**站内详情页路径**；不可跳转返回 ''（空串 = 不是"详情链接条目"）。
 *
 * 只有收藏更新通知（`kind === 'update'`，由 `comic_core.fanout` 发）带 `params.comicId`：
 * 判定唯一入口就在这里，页面只负责"有值就 push"，不自己读 params。
 */
export function detailPath(n: NoticeItem): string {
  if (n.kind !== 'update') return ''
  const p = n.params
  if (!p || typeof p !== 'object') return ''
  const id = Number((p as Record<string, unknown>).comicId)
  return Number.isInteger(id) && id > 0 ? `/comic/${id}` : ''
}
```

（`NoticeItem` 已在同文件 `:26` 定义并导出，无需额外 import。）

### 5.2 `comic-web/src/views/MessagesView.vue`

| 位置 | 现状 | 改成 |
|---|---|---|
| `:16` import 行 | `kindLabel, statusLabel, fmtMsgTime, paramSummary, useMessageStore` | 追加 `detailPath`（同一行末） |
| `:17` import 行 | `import { useRouter } from 'vue-router'` | **不动**（`router` 已就绪，`:20`） |
| `:21` `const msgStore = ...` 之后 | — | 新增 `function openItem(n: NoticeItem)`：`msgStore.markRead(n)`，`const path = detailPath(n)`，`if (path) router.push(path)` |
| `:71` `:class="[n.kind, n.status, { unread: !n.read }]"` | — | 追加 `linkable: !!detailPath(n)` → `[n.kind, n.status, { unread: !n.read, linkable: !!detailPath(n) }]` |
| `:72` `@click="msgStore.markRead(n)"` | 只标已读 | `@click="openItem(n)"` |
| `:174` 之后（样式块末尾） | — | 新增 `.msg-item.linkable { cursor: pointer; }`、`.msg-item.linkable:hover .msg-summary { color: var(--primary); text-decoration: underline; }` |

补充约定（给开发的自查项）：
- 类型 import：`NoticeItem` 从 `../stores/message` 里一并 import（它是 `export type NoticeItem`）。若嫌麻烦，参数写 `MessageItem` 亦可，但**别写 `any`**（`tsc --noEmit` 会过，但项目类型是有的）。
- **CSS 只写类选择器**（`comic-web/README.md:121`）：上面两条都是类选择器，合规；**不要**写 `.msg-item div:hover` 这类元素选择器。
- **不要**把 `openItem` 写成 `async`（`markRead` 不 await）；**不要**在模板里内联 `router.push`。
- 不改注释里已经写对的语义段；只在 `:72` 上方补一句「可跳转条目点整条进详情，其余只标已读」。

### 5.3 `comic-web/tests/message-detail-link.test.ts`（新增 · 测试角色）

纯函数用例，**不挂载组件**（与既有 `tests/season.test.ts` 同形）。矩阵：

| 输入 | 期望 |
|---|---|
| `{kind:'update', params:{comicId:12}}` | `'/comic/12'` |
| `{kind:'update', params:{comicId:'12'}}`（字符串） | `'/comic/12'` |
| `{kind:'update', params:{comicId:0}}` / `-3` / `'abc'` / `null` | `''` |
| `{kind:'update', params:null}` / `params:{}` | `''` |
| `{kind:'sync', params:{comicId:12}}`（任务消息误带） | `''` |
| `{kind:'update', params:{comicId:12, newChapters:3}}` | `'/comic/12'`（多键不影响） |

---

### 5.4 `comic-front/src/stores/message.ts`（在 `:100` 之后、`:102` `defineStore` 之前插入）

**改动 = §5.1 的代码块逐字复制**，不做任何平台适配（该文件是纯展示期归一，不碰 uni API）。位置与 web 完全对应：`paramSummary` 结束于 `:100`，`export const useMessageStore` 在 `:102`；`NoticeItem` 已在 `:26` 定义并导出。

差异点（写代码时唯一要注意的）：
- 注释里说明「与 comic-web 同名函数保持一致」——两端各一份，**改一处必须同步另一处**（没有共享包）。
- 其余 import（`computed, ref` / `defineStore` / `../api` / `../types`）**都不用动**。

### 5.5 `comic-front/src/pages/messages/index.vue`

> uni-app 形态：模板用 `view`/`text`，跳转仍走 `useRouter()` 兼容层（**不要**直接写 `uni.navigateTo`，那会绕开 `toUniUrl` 的路径映射与同页判断）。

| 位置 | 现状 | 改成 |
|---|---|---|
| `:17` import 行 | `import { kindLabel, statusLabel, fmtMsgTime, paramSummary, useMessageStore } from '../../stores/message'` | 追加 `detailPath`；类型 `NoticeItem` 另起 `import type { NoticeItem } from '../../stores/message'`（或与该行合并成 `type NoticeItem`） |
| `:18` `import { setRoute, useRouter } from '../../utils/router'` | — | **不动**（`router` 已在 `:21` 就绪，跳转不需要新增 import） |
| `:22` `const msgStore = useMessageStore()` 之后 | — | 新增 `function openItem(n: NoticeItem)`：`void msgStore.markRead(n)` → `const path = detailPath(n)` → `if (path) router.push(path)` |
| `:79` `:class="[n.kind, n.status, { unread: !n.read }]"` | — | 追加 `linkable: !!detailPath(n)` → `[n.kind, n.status, { unread: !n.read, linkable: !!detailPath(n) }]` |
| `:80` `@click="msgStore.markRead(n)"` | 只标已读 | `@click="openItem(n)"`；并在 `:79` 上方补一句注释「可跳转条目（收藏更新）点整条进详情，其余只标已读」 |
| `:182` 之后（`.msg-link:hover` 之后、`</style>` 之前） | — | 新增三条（见下） |

新增样式（**全部类选择器 + 伪类，符合 `comic-front/README.md:143` 的「CSS 只写类选择器」约定**）：

```css
/* 可跳转条目（收藏更新通知）：整条可点，与不可点的任务消息区分开 */
.msg-item.linkable { cursor: pointer; }
.msg-item.linkable:hover .msg-summary { color: var(--primary); text-decoration: underline; }
/* 触屏没有 hover —— 用按压态给移动端一个「这条能点」的即时反馈（只 front 加，web 无需） */
.msg-item.linkable:active { background: var(--primary-soft); }
```

补充约定（给开发的自查项）：
- **不要**把 `<view>` 换成 `<button>`：uni 的 `button` 带默认边框/背景，`uni-compat.css` 里还要额外覆盖，得不偿失；`<view @click>` 在本文件 `:62-67` 已有先例。
- **不要**直接调 `uni.navigateTo({ url: '/pages/comic/index?id=' + id })`：会绕过 `toUniUrl` 的映射与「同页不 navigateTo」判断，且把页面路径硬编码进消息页（将来改路径要改两处）。
- **不要**用 `v-model` / 自定义组件（本项目 `tests/conventions.test.ts` 会红）；本次也没引入任何组件。
- `openItem` **不写成 `async`**、不 `await markRead`（理由同 §3.2）。
- 该文件 `clearTimeout`/`onHide`/`onUnload` 那套已读时机**一个字都不改**（`:47-48`）。
- `:active` 只是提示层：**若 iOS 真机按压无反馈，不阻塞验收**，也不要改用 uni 的 `hover-class`（本项目无此先例，见 §6.2 R8）。

### 5.6 `comic-front/tests/message-detail-link.test.ts`（新增 · 测试角色）

- 用例矩阵**与 §5.3 完全相同**（同一份判定，两端必须给出同样答案）。
- import 写法对齐既有 `comic-front/tests/season.test.ts:6`：`import { detailPath } from '../src/stores/message'`。
- 该模块在 node 环境下**可 import**：`vitest.config.ts:12-17` 是 `environment: 'node'`，而 `stores/message.ts` 的 import 链（`../api` → `request/auth` → `utils/storage,event`）**模块级没有任何 `uni.*` 调用**（事实 #17）。
- ⚠️ 若真跑起来仍因 `uni` / `pinia` 运行时缺环境而失败：**停下来回报负责人**，不要自作主张把 `detailPath` 搬到新文件（那会变成第 7 个白名单外文件）。备选方案（需重新确认范围）是新增 `comic-front/src/utils/messageLink.ts`。

## 6. 影响面与风险

### 6.1 边界红线自查（角色卡要求）

| 红线 | 本次是否触碰 |
|---|---|
| `api-service` 只经 `comic_crawler.facade` | 否 —— **零后端改动** |
| `comic-core` 单向依赖（不依赖采集侧 / HTTP 框架） | 否 —— 不改 `comic_core` |
| `api` ↔ `scheduler` 三文件一写者 | 否 —— 不碰运行时数据文件 |
| 分层守卫 / 归层 | 否 —— 不新增 Python 模块 |
| 前端写法约定（原生标签 / 类选择器 / 不用裸 `localStorage`·`alert` / 自定义组件不用 `v-model`） | 本次只加一个 `@click` 与三条类选择器样式（含 `:hover`/`:active` 伪类），全部合规；两端 `tests/conventions.test.ts` 均不受影响 |
| uni-app 形态约定（模板用 `view`/`text`、跳转走 `useRouter` 兼容层、不改 `pages.json`） | 本次不动 `pages.json`、不直接调 `uni.navigateTo`，沿用页面已有的 `router`（`:18,21`），合规 |
| 性能红线（禁 N+1 / 逐条请求） | 否 —— **零新增请求**；`detailPath` 是 O(1) 纯函数，模板里每条调用一次（50 条上限，可忽略）；跳转是 `navigateTo` 压栈，不产生网络请求 |

### 6.2 风险与对策

| 风险 | 说明 | 对策 / 结论 |
|---|---|---|
| R1 作品已下架 | 发消息时 `list_favoriters(listed_only=True)` 已排除下架作品，但**消息发出后**作品仍可能被下架 → 点进去 404 | 接受。两端详情页都有人话兜底（web `ComicDetailView.vue:57-66`、front `pages/comic/index.vue:222-223`），不白屏、不报错。**不要**为它加前端 HEAD 探测（每条消息一次请求 = 性能红线） |
| R2 老消息缺 `comicId` | 若有历史 `update` 消息的 params 不是本形态（外部写者 / JSON 被截断） | 自动退化为原行为（只标已读），无报错。由验收 B（web）/ E（front）覆盖 |
| R3 `params` 被 2000 字符截断成非法 JSON | 理论上 JSON 断裂 → 后端 `_params_of` 返回 `None` → 前端拿不到 comicId | 收藏更新消息的 params ≈ 80 字符（3 个键），**当前不可能触发**；即便触发也只退化不报错 |
| R4 误触 | 整条可点 → 想选文字复制却跳走 | 消息正文极短，误触代价 = 一次返回；且**现有整条点击已经是"标记已读"**，热区不变只是动作更明确。点击区域已定「整条」（§8.1-②） |
| R5 未读角标 | 点完跳走，`markRead` 未 await | 离开页面整体标已读兜底落库，不会残留：web `onBeforeUnmount → markAllRead()`（`MessagesView.vue:40`）；front `onHide` + `onUnload → markAllRead()`（`pages/messages/index.vue:47-48`，跳详情只触发 `onHide`，本页仍在栈内） |
| R6 键盘可达性 | 条目是 `div` / uni `view`，键盘用户无法触发 | **沿用现状**（本页所有条目原本就不可键盘聚焦），不在本次放大。若要补需改 `role`/`tabindex`/`@keyup.enter`，属独立可访问性需求（已拍板不做，§8.1-③） |
| R7 双端不一致 | 两端各有一份 `detailPath` + 一份点击逻辑，**漏改 / 改歪一端**就是「网页能点、手机点不动」 | **已确认双端同批改**（§8.1-①）。防漏：验收 D/E 在 :5174 上真跑（§9.4、§9.5），范围门禁必须恰好 6 个文件（§9.0b） |
| R8 触屏没有 hover | web 用 `hover` 提示可点，触屏设备上永不触发 → 移动端「视觉可区分」目标失效 | front 额外加 `.msg-item.linkable:active`（按压变色，`--primary-soft`），仅 front 有、web 无 —— **行为一致、呈现手段按端适配**。⚠️ iOS Safari 的 `:active` 有时需要触摸监听才生效，若真机上按压无反馈：**接受**（跳转本身不受影响），**不要**为此引入 uni 的 `hover-class` —— 全站 17 个文件都用 CSS `:hover`，本项目没有该机制的先例 |
| R9 front 返回落点不同 | 从消息页进详情后，详情页「← 返回」走**写死层级** `parentOf('/comic/:id') = '/latest'`（`utils/router.ts:158`），不是消息页；web 走浏览器历史能退回消息页 | **接受，不在本次改**：这是 2026-10-09 用户指定的既有全局规则（刷新后仍有效），改它会波及所有详情页入口。若用户要求「返回消息页」，属独立需求（需引入 `from` 参数），见 §8.2-5 |
| R10 front 单测环境 | `vitest` 是 `environment: 'node'`，而 store 的 import 链经过 `uni` 封装层 | 已核对：`storage`/`event`/`request` 均**无模块级 `uni.*` 调用**（事实 #17），import 安全。若实测仍失败 → 停下回报，不擅自扩白名单（§5.6） |

## 7. 双端一致性（comic-web / comic-front）

**结论：已确认同步（用户 2026-10-22 拍板，§1.1-①）。两端同批改、同批验收，行为一致，实现手段按端适配。**

理由（决策依据，留痕）：
1. `AGENTS.md:19-20,34-35` 把两个前端定为**功能等价**（同一后端的两种上线形态：宿主 :5173 / :5174），只改一端 = 需求只完成一半，且违反成文约定。
2. 两端消息页与 store 是**逐行同构**的（`comic-front/src/pages/messages/index.vue:74-96` vs `comic-web/src/views/MessagesView.vue:66-88`；两份 `stores/message.ts` 的 `paramSummary` 一字不差），同步成本极低：镜像 3 处（store 加 `detailPath`、页面加 `openItem`、样式加 `.linkable`）。

### 7.1 两端差异点（只列「不一样的地方」，其余全部一致）

| 维度 | comic-web | comic-front | 是否影响行为 |
|---|---|---|---|
| 模板标签 | `div` | `view` / `text`（uni 组件） | 否 |
| 跳转调用 | `router.push('/comic/12')`（vue-router） | `router.push('/comic/12')` → 兼容层 `toUniUrl()` → `uni.navigateTo('/pages/comic/index?id=12')` | 否（同一入口 `router.push`，页面代码写法相同） |
| 详情页取参 | `route.params.id`（`ComicDetailView.vue:87`） | `onLoad(options)` 的 `options.id`（`pages/comic/index.vue:86-87`） | 否（由兼容层保证） |
| 路径登记 | `router.ts:66` 已有 `/comic/:id` | `utils/router.ts:93-94` 已有 `/^\/comic\/\d+$/` 分支，**无需新增登记** | 否 |
| 返回落点 | 浏览器历史 → 可退回消息页 | 写死层级 → `/latest`（`utils/router.ts:158`） | **是**，但属既有全局行为，本次不改（R9） |
| 可点提示 | `cursor: pointer` + `:hover` 标题变色下划线 | 同左，**另加** `:active` 按压底色（触屏无 hover，R8） | 否（只是提示手段） |
| 单测 | `comic-web/tests/message-detail-link.test.ts` | `comic-front/tests/message-detail-link.test.ts`（同矩阵，独立文件） | 否 |
| 自查命令 | `npm run typecheck / lint / test / build` | `npm run typecheck / lint / test` + `npm run build:h5` | 否 |

**不变的东西（必须完全一致，验收时逐条对）**：判定规则（只认 `kind === 'update'`、`comicId` 为正整数）、点击顺序（先 `markRead` 不 await、后跳转）、已读时机（不点也照旧离开页面整体标）、不可点条目的原行为、零新增请求。

## 8. 待拍板事项

### 8.1 已拍板（2026-10-22，用户三项全按推荐，无需再问）

| # | 事项 | 结论 | 落点 |
|---|---|---|---|
| ① | 是否同步 comic-front | **同步做** | §1.1、§4（白名单已扩为 6 个文件）、§5.4-5.6、§7 |
| ② | 点击区域：整条 vs 只有标题 | **整条消息可点** | §3.2、§5.2 `:72`、§5.5 `:80` |
| ③ | 是否补键盘可达性 | **本次不做**（条目仍是 `div`/`view`） | §1 非目标、§6.2 R6 |

### 8.2 仍需用户拍板（都不阻塞开发，可先按推荐实现）

4. **`linkable` 的视觉强度**（推荐：现状 = `cursor` + 标题变色下划线 + front `:active` 底色）。可选项：更弱的「仅 `cursor: pointer`」；或更强的「左侧 3px 主题色竖条」。**默认按推荐实现**，用户若觉得太素/太重，改一行样式即可。
5. **front 详情页「← 返回」落点**（§6.2 R9）：从消息页进去后返回落到 `/latest` 而非消息页 —— 这是既有全局规则（刷新后仍有效），**本次不改**。若用户要求「从哪来回哪去」，需另开任务给详情页加 `from` 参数（会波及全部详情页入口，不建议塞进本任务）。

（原「是否同步 comic-front」「整条 vs 标题」「键盘可达性」三条已关闭，见 §8.1。）

## 9. 验收标准（可执行）

> 环境：**两端都起** —— `cd comic-web && npm run dev`（:5173）、`cd comic-front && npm run dev:h5`（:5174）、后端 uvicorn :8000 已起。
> Playwright MCP 可用（`AGENTS.md:74` 要求前端问题必须真跑取证）。**以下命令设计阶段未执行**（设计只读代码）。

### 9.0 静态门禁（两端各 4 条，必过）

```bash
# comic-web（:5173）
cd comic-web && npm run typecheck     # 期望：无输出、退出码 0
cd comic-web && npm run lint          # 期望：无 error
cd comic-web && npm run test          # 期望：既有 4 个用例 + 新增 detailPath 用例全绿
cd comic-web && npm run build         # 期望：build 成功（Vite 产物）

# comic-front（:5174，uni-app）—— 注意 dev/build 脚本名带 :h5
cd comic-front && npm run typecheck   # 期望：无输出、退出码 0
cd comic-front && npm run lint        # 期望：无 error
cd comic-front && npm run test        # 期望：既有 4 个用例 + 新增 detailPath 用例全绿
cd comic-front && npm run build:h5    # 期望：uni build 成功
```

### 9.0b 范围门禁（1 条）

```bash
git status --porcelain   # 期望 = 4 个源码文件（M）+ 2 个新增 tests 文件（??）
```

期望清单（顺序无关）：`comic-web/src/stores/message.ts`、`comic-web/src/views/MessagesView.vue`、`comic-web/tests/message-detail-link.test.ts`、`comic-front/src/stores/message.ts`、`comic-front/src/pages/messages/index.vue`、`comic-front/tests/message-detail-link.test.ts`。

任何白名单外文件出现 → 直接判失败（`types.ts`、`utils/router.ts`、`pages.json`、`Layout.vue`、后端任何文件出现即违规）。

### 9.1 验收 A（comic-web · :5173）：`kind === 'update'` 且 `params.comicId` 有效 → 跳到详情页且作品名一致

**前置数据（确认库里真有这种消息）**：

```sql
-- 走 mcp__comic-mysql__execute_query，或
-- docker exec comic-mysql mysql -uroot -p"$COMIC_MYSQL_ROOT_PASSWORD" comic -e "..."
SELECT id, title, JSON_UNQUOTE(JSON_EXTRACT(params, '$.comicId')) AS comic_id,
       to_user_id, created_at
FROM message WHERE kind = 'update' ORDER BY id DESC LIMIT 5;
```
- 判定：至少 1 行且 `comic_id` 非 NULL。记下 `to_user_id`（用它登录，否则看不到定向消息）。
- 期望详情页标题：把 `title` 里的书名号内容取出（`《X》更新了` → `X`），与 `SELECT title FROM comic WHERE id = <comic_id>` 一致。

**操作 + 检查点（Playwright）**：
1. 用该 `to_user_id` 对应账号登录 → `browser_navigate('http://127.0.0.1:5173/#/messages')`。
2. `browser_snapshot` → 找到该 `update` 条目；判定其**存在 `linkable` 类**（DOM 里 `class="msg-item update done linkable"`，顺序可变）。
3. `browser_click` 该条目 → `browser_evaluate(() => location.hash)` **必须等于** `#/comic/<comic_id>`。
4. `browser_snapshot` → 详情页 `<h1>`（`ComicDetailView.vue:232` 的 `u-h1`）文本 **等于** `comic.title`；`browser_console_messages` 无 error。
5. 回归已读：`browser_network_requests` 里应有 `POST /api/messages/<id>/read`（或对应已读接口）；返回消息页后该条**不再有 `unread` 类**。

### 9.2 验收 B（comic-web）：`params.comicId` 缺失 → 不加链接，点击只标已读

**取一条无 comicId 的条目**：任务消息最省事（`kind='sync'` 等，`min_role='admin'`，用管理员账号）：

```sql
SELECT id, kind, title, params FROM message
WHERE kind <> 'update' ORDER BY id DESC LIMIT 5;
```

**检查点（Playwright，页面仍是 `/#/messages`）**：
1. 该条目 DOM **不含** `linkable` 类；hover 时标题不变色（可截图对比，`browser_take_screenshot`）。
2. `browser_click` → `location.hash` **仍为** `#/messages`（未跳转）。
3. 该条 `unread` 类消失 / `msgStore.unread` 数值 -1 → 说明「只标已读」仍生效。
4. 若库里有历史 `update` 消息但 `params` 无 `comicId`（可用 `WHERE kind='update' AND JSON_EXTRACT(params,'$.comicId') IS NULL` 查），同样必须满足 1~3 —— 这条是**老消息退化**的关键回归。

### 9.3 验收 C：登录 / 未登录两态

| 场景 | 检查点 |
|---|---|
| **已登录**（收藏者本人） | 9.1 全流程通过；消息页可刷新、未读数正确 |
| **未登录**打开 `/#/messages` | `location.hash` 变为 `#/login?redirect=%2Fmessages`（现有门卫行为不变）：web `MessagesView.vue:28-31`、front `pages/messages/index.vue:30-33,36`：`browser_navigate` → `browser_evaluate(location.hash)` |
| **未登录**直接打开 `/#/comic/<comic_id>` | 详情页正常渲染标题（**不**跳登录页）——证明跳转目标本身无登录门槛（`ComicDetailView.vue:93` 只在收藏/评论处要登录）|
| **另一账号**（非收藏者）打开消息页 | 看不到该条定向消息（`to_user_id` 过滤），页面上没有可点条目 → 无 404 / 无空白 |

未登录态获取方式：`browser_evaluate(() => { localStorage.clear(); location.reload() })`（**仅测试期临时用**；应用代码里禁止裸 `localStorage`，见 `README.md:122`）。

### 9.4 验收 D（comic-front · :5174）：移动端点 `update` 条目 → 跳到对应详情页

> 与验收 A 用**同一条数据**（同一 `comicId`），两端结果必须一致 —— 这就是「双端功能等价」的可观察定义。

**操作 + 检查点（Playwright，`http://127.0.0.1:5174`）**：
1. 同账号登录 → `browser_resize(390, 844)`（移动视口）→ `browser_navigate('http://127.0.0.1:5174/#/messages')`。
2. `browser_snapshot` → 该 `update` 条目**含 `linkable` 类**（`.msg-item update done linkable` 形态）。
3. `browser_click` 该条目。
4. **URL 检查**：`browser_evaluate(() => location.hash)` 必须命中 `#/pages/comic/index?id=<comic_id>` —— 兼容层产出的是 **uni 页面路径 + `id` 参数**（`utils/router.ts:93-94`），**不是** `#/comic/<id>`。这是与 web 的唯一形态差异，**不要当成 bug**。
5. **页面检查**：详情页标题 `.u-h1`（`pages/comic/index.vue:233`，文本 = `comic.title`）**等于** `<comic.title>`；`browser_console_messages` 无 error（尤其不应出现 `[router] 未登记的 web 路径` 警告 —— 出现即说明走了 `utils/router.ts:101-102` 的兜底回首页）。
6. 回归已读：`browser_network_requests` 有对应已读请求；`browser_evaluate` 回看 store 或返回消息页后该条**不再有 `unread` 类**。
7. 触屏反馈（R8）：该可点条目按下时背景变 `--primary-soft`（截图对比，非强制项）。

### 9.5 验收 E（comic-front）：无 `comicId` 的条目**不跳**、只标已读

**操作 + 检查点（同 :5174，页面停在 `#/messages`）**：
1. 取任务类条目（`kind='sync'/'schedule'` 等，管理员账号可见）→ DOM **不含** `linkable` 类。
2. `browser_click` → `location.hash` **仍为** `#/messages`（未跳转、未出现 `pages/comic`）。
3. 该条 `unread` 类消失 / 未读数 -1 → 「只标已读」仍生效。
4. 历史 `update` 但 `params` 无 `comicId` 的条目（SQL 见 9.2）同样满足 1~3。

### 9.6 回归（不能被本次改动破坏）

1. 消息页「全部已读」「刷新」「← 返回」三个按钮点击**不触发跳转**（它们是 `.title-row` 内的按钮，不在 `.msg-item` 内 —— 快照确认无需 `@click.stop`；若实现时把 `openItem` 误挂到容器上，此条会红）。**两端各验一次**。
2. 顶栏铃铛角标、轮询（空闲 60s）行为不变（`:5173` / `:5174` 各一次）。
3. 任务结果 toast 仍只弹不跳（两端 `Layout.vue` 均未改）。
4. 窄屏（375×667）与宽屏（1280×800）下 `.msg-item` 布局不溢出：`browser_resize` + 截图（两端）。
5. **front 专项**：详情页「← 返回」落到 `/latest`（既有层级规则，R9）—— 记录现状即可，**不算本次回归失败**；但必须确认它没有变成空白页或回首页。

## 10. 给开发的最小自查清单

**两端共同**
- [ ] 白名单 **4 个源码文件**（web 2 + front 2），无其它改动（`git status --porcelain`）
- [ ] `detailPath` 在两端 store 里都 export，页面**只调用**不重复实现判定
- [ ] **两份 `detailPath` 函数体逐字相同**（复制粘贴后比对一次，别"顺手优化"其中一份）
- [ ] 点击顺序：`markRead` 在前（不 await）、`push` 在后
- [ ] `linkable` 只在 `detailPath` 非空时加
- [ ] 未 commit（任务卡「提交策略：不自动提交」）

**comic-web**
- [ ] 样式只用类选择器、无内联样式、无 `!important`
- [ ] 改完重启 Vite（`AGENTS.md:68`）

**comic-front（uni-app）**
- [ ] 模板仍是 `view`/`text`，**没**换成 `button`、**没**加自定义组件（`v-model` 守卫）
- [ ] 跳转走 `router.push(path)`，**没有**直接调 `uni.navigateTo` 或硬编码 `pages/comic/index`
- [ ] 没动 `pages.json`、`utils/router.ts`（`/comic/<id>` 分支已存在）
- [ ] 样式只用类选择器（含 `:hover`/`:active` 伪类），无内联样式
- [ ] `npm run dev:h5` 重新起（uni 的 HMR 对 `pages.json`/插件更敏感，改完源码也建议重启一次）
