# `TASK-20261023-01` 实现 · 收藏「新」角标 + 最近阅读点封面跳详情

## 1. 一句话结论

6 个文件全部在白名单内（web 3 / front 3）；两端 lint / typecheck / vitest 全绿（web 27 passed、front 33 passed）；无功能偏差，仅有 2 处按 uni-app 约定的等价替换（`span`→`text`、无 `v-model`）。

---

## 2. 改动清单

| # | 文件 | 动作 | 摘要 |
|---|---|---|---|
| 1 | `comic-web/src/utils/favorite.ts` | 新增 | `buildReadAtMap` / `hasUpdate` 两个纯函数：`Date.parse` 转毫秒后比较，任一侧缺失/不可解析 → false |
| 2 | `comic-web/src/views/MeView.vue` | 修改 | import `computed` + favorite 工具；新增 `goDetail` / `readAtMap`；最近阅读行 `@click` 改 `goDetail`，续读按钮加 `.stop`；`fav-thumb` 内加「新」角标 + CSS |
| 3 | `comic-web/tests/favorite.test.ts` | 新增 | 8 条用例（6 条判定 + 2 条建索引），含等号、时区、无历史、空 `updatedAt` |
| 4 | `comic-front/src/utils/favorite.ts` | 新增 | 与 web **函数体逐字一致**（仅头注释点明双端同步） |
| 5 | `comic-front/src/pages/me/index.vue` | 修改 | 与 web 对称：uni 组件（`<text>` 角标）、`router.push('/comic/' + id)` 走既有兼容层、续读按钮 `@click.stop` |
| 6 | `comic-front/tests/favorite.test.ts` | 新增 | 与 web **同一组 8 条用例**（双端判定必须等价） |

**是否全部在白名单内**：`是`

---

## 3. 关键实现点

| 设计点 | 实现方式 |
|---|---|
| §5.1 `favorite.ts` | `comic-web/src/utils/favorite.ts:31` `buildReadAtMap`（跳过 `Number.isNaN(Date.parse)` 的条目、同 `comicId` 取最大值）、`:47` `hasUpdate`（无 `updatedAt`→false、`readAtMap` 查不到→false、`Date.parse` 不可解析→false、否则 `>` 严格大于） |
| §5.2 import 区 | `comic-web/src/views/MeView.vue:2` 加 `computed`；`:11` 加 `import { buildReadAtMap, hasUpdate } from '../utils/favorite'` |
| §5.3 `goDetail` + `readAtMap` | `comic-web/src/views/MeView.vue:45` `goDetail(h)` → `router.push('/comic/' + h.comicId)`（同标签页）；`:50` `const readAtMap = computed(() => buildReadAtMap(history.value))` |
| §5.4 行级点击 | `MeView.vue:72` `@click="goDetail(h)"`；封面 `<img>` 与标题区不绑事件，靠冒泡（点封面 = 点行 = 详情） |
| §5.5 续读按钮 | `MeView.vue:80` `@click.stop="continueRead(h)"`；外层 `.row-actions` 的 `@click.stop` 保留（`:79`），双保险 |
| §5.6 角标 DOM | `MeView.vue:98` `<span v-if="hasUpdate(c, readAtMap)" class="fav-badge">新</span>`，插在 `fav-thumb` 的 `img` 之后（与封面同盒） |
| §5.7 角标 CSS | `MeView.vue:172` `.fav-badge`：`absolute / top:6px / right:6px / z-index:1 / border-radius:999px / font-size:11px / pointer-events:none`；`fav-thumb` 本就 `position: relative`（`:161`） |
| §5.8 单测 | `comic-web/tests/favorite.test.ts` 仿 `season.test.ts`（vitest，只 import 纯函数，无 DOM/uni 依赖） |
| front 等价 | `comic-front/src/pages/me/index.vue:74/82/100/174` 与 web 一一对应；`router` 来自 `utils/router.ts`（`/comic/<id>` → `pages/comic/index?id=`，`router.ts:93` 已有映射，**`pages.json` 未改**）；角标用 `<text>`（uni 的 span 等价物） |
| 收藏卡整卡跳详情 | 未改动（`MeView.vue:95` / `index.vue:97` 原 `@click="router.push(...)"` 保持原样），角标 `pointer-events: none` 保证不产生死区 |

---

## 4. 单测覆盖矩阵

| # | 用例 | 覆盖场景 | 期望 |
|---|---|---|---|
| 1 | 更新晚于阅读 | `updatedAt` = 10-02，`readAt` = 10-01 | `true` |
| 2 | 更新早于阅读 | `updatedAt` = 10-01，`readAt` = 10-02 | `false` |
| 3 | 更新与阅读相等 | 两侧同一时刻 | `false`（等号不算"晚于"） |
| 4 | 从未读过 | `readAtMap` 无该 id / 空历史 | `false` |
| 5 | `updatedAt` 为空 | `''` / `null` / 缺字段 | `false` |
| 6 | 时区写法不同 | `Z` vs `+08:00`（两个方向各一断言） | 换算成 UTC 后比较，结果正确 |
| 7 | 同作品多条历史取最大 | 3 条不同 `readAt` + 另 1 作品 | 各取最后一次 |
| 8 | 坏 `readAt` 跳过 | `'坏数据'` + 合法条目 / 空数组 | 合法条目入表、空表 size = 0 |

---

## 5. 自测结果

| # | 命令 | 实际结果 |
|---|---|---|
| 1 | `cd comic-web && npm run lint` | 0 error / 0 warning |
| 2 | `cd comic-web && npm run typecheck` | 0 error |
| 3 | `cd comic-web && npx vitest run` | 6 files / 27 tests passed，0 failed（其中 `favorite.test.ts` 8 passed） |
| 4 | `cd comic-front && npm run lint` | 0 error / 4 warning（全部在 `src/pages/reader/index.vue`，既有 `no-explicit-any`，非本次文件） |
| 5 | `cd comic-front && npm run typecheck` | 0 error |
| 6 | `cd comic-front && npx vitest run` | 6 files / 33 tests passed，0 failed（其中 `favorite.test.ts` 8 passed；`router.test.ts` 的 `console.warn` 是「未登记路径」用例的预期输出） |

**未跑项**：`build`（本次无构建配置/依赖改动，且设计与任务书均未要求）；`Playwright / 启动 dev server`（浏览器交互验证属测试角色，按任务书不在 dev 范围）。

---

## 6. 与设计的偏差

- 偏差 1：`comic-front/src/pages/me/index.vue:100` 角标元素用 `<text>` 而非 `<span>` —— uni-app 模板只允许 uni 组件（设计 §3.2 的 `<span>` 是 web 写法）；视觉与行为一致，CSS 仍只写类选择器。影响：无。
- 偏差 2：设计 §2 / §4 写「comic-front 默认不动」，实际按用户拍板双端同步，新增 front 侧 3 个文件（`utils/favorite.ts`、`pages/me/index.vue`、`tests/favorite.test.ts`）—— 属**已知范围变更**（负责人已下发的白名单第 4~6 项），非自行扩范围。
- 其余（文件清单、判定规则、角标定位、点击分流、`.stop` 双保险）与设计 §5 逐条一致。

---

## 7. 遗留与风险处理

| 编号 | 处理结果 |
|---|---|
| R1 | 按设计**接受**：角标基于 `comic.sync_time`，元数据变更也会亮。判定函数注释已写明口径，不改。 |
| R2 | 按设计**接受**：历史接口条数受限时更早读过的收藏不亮（漏报不误报）。`hasUpdate` 对「查不到 `readAt`」显式返回 false，正是这一取舍。 |
| R3 | 语义说明已在 `favorite.ts` 头注释写明「不是有未读章节」；建议验收说明沿用设计 §7 措辞。 |
| R4 | 已按设计处理：续读按钮位置/文案不变，只是点击面从「整行」变「整行详情 + 按钮续读」；榜单等其它页面未受影响。 |
| R5 | 已处理：`.fav-badge` 带 `pointer-events: none`（web `MeView.vue:178` / front `index.vue:180`），点角标区域仍触发整卡跳详情。 |

---

## 备注

### 双端一致性

- 两个 `favorite.ts` 的 `buildReadAtMap` / `hasUpdate` **函数体逐字一致**，两份测试用例也一致 —— 后续改动必须同步两份，头注释已互相点名。
- 两端 vitest 均只测纯函数（`favorite.ts` 不 import 任何 uni / vue 模块），因此 front 的 vitest 未受 `uni.*` 影响，无需改测试配置。

### 验证建议（给测试角色）

- 角标三态：A（`updatedAt` > 最近 `readAt`）亮、B（读过且之后未更新）不亮、C（从未读过）不亮；点角标区域应仍跳详情。
- 最近阅读：点封面 → `/#/comic/<id>`（同标签页）；点「续读」→ 新标签页 `/#/reader/<comicId>/<chapterId>` 且不触发详情跳转；点「删除」只删记录。
- 收藏卡整卡跳详情保持不变。
