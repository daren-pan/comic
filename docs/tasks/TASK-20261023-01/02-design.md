# `TASK-20261023-01` 设计 · 收藏「新」角标 + 最近阅读点封面跳详情

> **⚠️ 决策变更（2026-10-23 15:22，用户拍板）**
> 本设计定稿时把「是否同步 comic-front」列为待拍板、默认不动。**用户随后选择「双端同步」**，白名单因此从 3 个文件扩为 **6 个**（新增 `comic-front/src/utils/favorite.ts`、`comic-front/src/pages/me/index.vue`、`comic-front/tests/favorite.test.ts`）。
> 本文 §2 / §4 / §8 里"默认不动 front""跨模块：否""待拍板 ①"等表述**已被此决定覆盖**，实现以 6 文件白名单为准。

## 1. 一句话结论

纯前端可解，后端接口已带齐字段（收藏 `Comic.updatedAt` / 历史 `HistoryEntry.readAt`）；改 `comic-web` 3 个文件（1 新增工具 + 1 改视图 + 1 新增测试），**不跨模块**（comic-front 是否同步列为待拍板，默认不动）。

---

## 2. 目标与非目标

### 目标（完成态）

- 「我的收藏」里，凡**上次阅读之后作品有更新**的收藏，封面右上角显示「新」角标；无更新/未读过的不显示。
- 「最近阅读」点**封面**（含该行标题区）跳 `/comic/<id>` 详情页；「续读」按钮仍跳 `/reader/<comicId>/<chapterId>` 阅读器，两者互不误触。
- 收藏卡整卡跳详情的现有行为保持不变。

### 非目标（明确不做）

- 不改后端接口、不加新字段、不改 `comic.sync_time` 的写入语义（不引入"已读角标"持久化状态）。
- 不做「角标点掉/已读清零」的交互（未读状态完全由时间比对推导，天然随下一次阅读消解）。
- 不改首页 / 最近更新页 / 详情页的「新」角标逻辑。
- 不同步 `comic-front`（uni-app 端）——见 §8 待拍板 ①。

---

## 3. 方案

### 3.1 「有更新」判定规则

- 现状：收藏列表只展示封面/标题/话数，更新与否完全不可见；用户须进详情页才知道有新章节。
- 改为：抽 `comic-web/src/utils/favorite.ts`，纯函数、无副作用，便于单测：
  - `buildReadAtMap(history)` → `Map<comicId, readAtMs>`：把历史列表压成「本作品最后一次阅读时间」。
  - `hasUpdate(comic, readAtMap)` → `boolean`：`updatedAt` 与 `readAt` 均按 `Date.parse()` 转毫秒比较，**`updatedAtMs > readAtMs` 才为 `true`**；任一缺失/不可解析（含无历史记录）一律 `false`。
  - 用 `Date.parse` 而非字符串比较：两侧虽同为 ISO 8601，但时区写法可能不同（`Z` / `+08:00`），字符串比较会误判。
- 视图侧用 `computed` 由 `history` 派生 `readAtMap`，模板里 `hasUpdate(c, readAtMap)` 直接调用（收藏 ≤ 一屏，开销可忽略）。

### 3.2 角标渲染

- 位置：放在 `fav-thumb` 内、`img` 之后，作为 `fav-thumb` 的绝对定位子元素（`fav-thumb` 已是 `position: relative`，见 `MeView.vue:158`），贴 `top/right: 6px`，`z-index: 1` 盖住封面。
- 视觉：`--primary` 底 + 白字、`border-radius: 999px`、`font-size: 11px`，文案固定「新」。
- **`pointer-events: none`**：角标不拦截点击，收藏卡整卡 `@click` 行为零改动。
- 不加额外状态标记，`v-if` 直接吃 `hasUpdate` 结果。

### 3.3 最近阅读点击分流

- 现状：整行 `.row` 绑 `@click="continueRead(h)"`（`MeView.vue:62`）→ 跳阅读器；`.row-actions` 用 `@click.stop`（`:69`）隔离按钮。
- 改为：
  1. `.row` 的 `@click` 换成 `goDetail(h)` → `router.push('/comic/' + h.comicId)`；封面 `<img class="row-cover">`（`:63`）不另绑事件，点击自然冒泡到行 → 详情页（同时标题区点击也进详情，与收藏卡整卡可点一致）。
  2. `.row-actions` 的 `@click.stop` **保留**（`:69`）；「续读」按钮（`:70`）再显式加 `.stop`：`@click.stop="continueRead(h)"`，双保险，防止将来重构掉外层包装后按钮误触发详情跳转。
  3. 「删除」按钮不动。
- 结果：点封面/文字 → 详情；点续读 → 阅读器；点删除 → 删记录。三者互不干扰。

---

## 4. 文件级白名单

| # | 文件 | 端 / 模块 | 动作 |
|---|---|---|---|
| 1 | `comic-web/src/utils/favorite.ts` | comic-web | 新增 |
| 2 | `comic-web/src/views/MeView.vue` | comic-web | 修改 |
| 3 | `comic-web/tests/favorite.test.ts` | comic-web | 新增 |

**是否跨模块**：`否`（仅 comic-web）。`comic-front`（uni-app 端「我的」页存在同款列表）**未获用户点名，默认不动**；如需双端等价，见 §8 ①。

---

## 5. 改动清单

### 5.1 `comic-web/src/utils/favorite.ts`（新增，约 30 行）

- 现状：`utils/` 下无收藏相关工具（现有 `format/season/nav/...`），判定逻辑零散无处放。
- 改动：
  ```ts
  export function buildReadAtMap(history: { comicId: number; readAt: string }[]): Map<number, number>
  export function hasUpdate(
    comic: { id: number; updatedAt?: string | null },
    readAtMap: Map<number, number>,
  ): boolean
  ```
  - `buildReadAtMap`：遍历 history，`Date.parse(readAt)`，非法值跳过，同 `comicId` 取最大值。
  - `hasUpdate`：无 `updatedAt` → false；`readAtMap` 无该 `id` → false；否则 `Date.parse(updatedAt) > readAt`。
- 理由：把"时间比对"从模板里剥出来，可单测、可复用（将来 comic-front 或详情页也能用）。

### 5.2 `comic-web/src/views/MeView.vue:2`（import 区）

- 现状：`import { onMounted, ref } from 'vue'`。
- 改动：改为 `import { computed, onMounted, ref } from 'vue'`；并在 `:10` 后新增 `import { buildReadAtMap, hasUpdate } from '../utils/favorite'`。
- 理由：需要 `computed` 派生 `readAtMap`。

### 5.3 `comic-web/src/views/MeView.vue:38`（新增 `goDetail` + `readAtMap`）

- 现状：`continueRead(h)` 直接 `openNewTab('/reader/...')`；`:42` 处是一条孤立注释。
- 改动：
  - `:41` 后新增 `function goDetail(h: HistoryEntry) { router.push('/comic/' + h.comicId) }`（同一标签页内跳转，与收藏卡一致）。
  - `:42` 前新增 `const readAtMap = computed(() => buildReadAtMap(history.value))`。
- 理由：点击分流需要新的跳转函数；角标判定需要历史时间索引。

### 5.4 `comic-web/src/views/MeView.vue:62`

- 现状：`<div v-for="h in history" :key="h.comicId" class="row" @click="continueRead(h)">`
- 改动：`@click="goDetail(h)"`（封面 `:63` 与标题区不加事件，靠冒泡）。
- 理由：需求要求「点封面 → 详情」。

### 5.5 `comic-web/src/views/MeView.vue:70`

- 现状：`<button class="btn ghost sm u-button" @click="continueRead(h)">续读</button>`
- 改动：`@click.stop="continueRead(h)"`（外层 `:69` 的 `@click.stop` 保留）。
- 理由：`.stop` 显式化，保证续读不进详情页。

### 5.6 `comic-web/src/views/MeView.vue:86-88`

- 现状：`<div class="fav-thumb"><img class="u-img" ... /></div>`
- 改动：`img` 之后插入 `<span v-if="hasUpdate(c, readAtMap)" class="fav-badge">新</span>`。
- 理由：角标必须与封面同盒定位。

### 5.7 `comic-web/src/views/MeView.vue:159`（CSS）

- 现状：`.fav-thumb .u-img { position: absolute; ... }` 之后无角标样式。
- 改动：新增
  ```css
  .fav-badge {
    position: absolute; top: 6px; right: 6px; z-index: 1;
    padding: 1px 6px; border-radius: 999px;
    background: var(--primary); color: #fff;
    font-size: 11px; font-weight: 600; line-height: 16px;
    pointer-events: none;
  }
  ```
- 理由：`fav-thumb` 已 `position: relative`（`:158`），直接绝对定位即可；`pointer-events: none` 保证不吞点击。

### 5.8 `comic-web/tests/favorite.test.ts`（新增）

- 现状：无。
- 改动：仿 `comic-web/tests/season.test.ts` 用 vitest，覆盖：更新晚于阅读 → true；早于/相等 → false；无历史 → false；`updatedAt` 为空 → false；时区不同写法（`Z` vs `+08:00`）比较正确；`buildReadAtMap` 取最大 `readAt`。
- 理由：时间比较是最易写错的一处（时区、等号）。

---

## 6. 影响面与风险

| 编号 | 风险 / 影响面 | 处理方式 |
|---|---|---|
| R1 | 「有更新」基于 `comic.sync_time`（=`updatedAt`），**元数据变更（改标题/简介/封面）也会刷新同步时间**，造成无新章节却亮「新」 | 本次接受（与「最近更新」列表口径一致）；单据文案是"更新标志"，非"新章节" |
| R2 | `getHistoryWithDetail` 返回条数受限（最近约 50 条），更早读过的收藏查不到 `readAt` → 永远不亮 | 本次接受，属漏报不误报；后续可要后端提供「按 comicId 批量查最后阅读时间」接口（非本次范围） |
| R3 | 语义是"我上次读后作品变过"，**不等于"有未读章节"**；读到最后一章后作品再更一章才亮，符合预期但需在验收说明中写清 | 写入 §7 验收说明，避免后续被当 bug |
| R4 | 最近阅读行点击面从"整行续读"变为"整行详情"，老用户肌肉记忆可能误以为进阅读器 | 续读按钮保留且位置不变；角标式交互与收藏页一致 |
| R5 | 角标若不加 `pointer-events: none`，点角标区域会让收藏卡"死区" | 已在 §5.7 固定该属性 |

**边界红线自查**：

- [x] `api-service` 只经 `comic_crawler.facade` — 不涉及（无后端改动）
- [x] `comic-core` 不依赖采集侧 / HTTP 框架 — 不涉及
- [x] api ↔ scheduler 三文件一写者 — 不涉及
- [x] 新增模块已归层 — 新增的是前端 `utils/` 纯函数，符合现有 `utils/season.ts` 同类归位
- [x] 前端双端等价（`comic-web` / `comic-front`）已判断 — **本次只做 comic-web**，comic-front 待拍板（§8 ①）

---

## 7. 验收标准

| # | 验收项 | 怎么验（命令 / 检查点） | 期望结果 |
|---|---|---|---|
| 1 | 有更新显示「新」、无更新不显示 | 在 `comic-web` 启动后：收藏 A（`updatedAt` > 最近 `readAt`）、B（读过且之后未更新）、C（从未读过），进「我的 -> 我的收藏」 | A 封面右上角有「新」；B、C 无角标；点角标区域仍能跳详情 |
| 2 | 最近阅读点封面 → 详情页 | 点「最近阅读」中任一行的**封面** | 同标签页跳到 `/#/comic/<id>`，不是阅读器 |
| 3 | 最近阅读点续读 → 阅读器 | 点同一行的「续读」 | 新标签页打开 `/#/reader/<comicId>/<chapterId>`，且**不**同时触发详情跳转 |
| 4 | 收藏页整卡跳详情行为不变 | 点任一收藏卡封面/标题/话数 | 跳 `/#/comic/<id>` |
| 5 | 单测与类型检查 | `cd comic-web && npm run test && npm run typecheck` | 全绿；`favorite.test.ts` 覆盖 6 条用例 |

**未实跑声明**：设计阶段只读代码，以上命令 `已跑 0 条 / 已跑 0 条`。

**语义说明**（对应 R3）：角标含义是「你上次读这本之后，作品有过更新」，不是「有未读章节」。故读到最新章后再更新才亮；从未读过的收藏不亮（见 §8 ②）。

---

## 8. 待拍板

| # | 问题 | 选项 | 推荐 | 影响 |
|---|---|---|---|---|
| 1 | 是否同步 `comic-front`（uni-app 端） | A. 本次只做 comic-web<br>B. 双端一起做（需新增 `comic-front` 侧工具 + 我的页改动，属跨模块） | **A**（需求表影响模块只写了 comic-web，且用户未点名 front） | 不做则小程序/H5 端无角标、点封面仍是续读，双端体验不一致 |
| 2 | 从未读过的收藏是否点亮「新」 | A. 不亮（需有 `readAt` 才比较）<br>B. 一律点亮（当作"有更新待看"） | **A**（无基准时间就只能噪点，收藏夹刚加入时全亮等于失效） | 选 B 会让新收藏的书全部亮角标，用户无法分辨 |

---

## 备注（选填）

### 事实核对

- 收藏接口返回 `Comic[]`，`Comic.updatedAt` 存在 → `comic-web/src/api/user.ts:125`、`comic-web/src/types.ts:31`
- 历史接口返回 `HistoryEntry & { comic?, chapterTitle? }`，`readAt` 为字符串 → `comic-web/src/api/user.ts:182`、`comic-web/src/types.ts:91-96`
- 最近阅读行当前整行跳阅读器 → `comic-web/src/views/MeView.vue:62`，`continueRead` 定义在 `:38-41`
- `.row-actions` 已有 `@click.stop` → `comic-web/src/views/MeView.vue:69`
- 收藏卡整卡跳详情 → `comic-web/src/views/MeView.vue:85`；`.fav-thumb` 已是 `position: relative` → `:158`
- `utils/` 下无 `favorite.ts`（现有 `event/format/icons/layout/nav/season/storage/theme/ui`）
- 测试放在 `comic-web/tests/*.test.ts`（vitest），命令 `npm run test` → `comic-web/package.json:11`

### 参考

- `comic-web/tests/season.test.ts`（同类纯函数单测写法）
- `docs/tasks/_template/02-design.md`
