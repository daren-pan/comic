# comic-web · 知识库（AI 维护）

> 本文件是 comic-web 的**踩坑与知识沉淀**，由 AI 协作时维护 ——
> **每次踩坑 / 实测 / 复盘写到这里**，不再写进 `README.md`（README 只放模块框架、约定与用途，给人看）。
> 各页面的**具体逻辑**由其源码注释解释维护，这里只放「为什么」与「踩过的坑」。

## 条目模板（新增知识时按此写）

**坑 / 决策 / 事实 —— 一律用这个字段块**（有就写、没有可省，字段名保持一致）：

```markdown
#### 标题（一句话说清是什么）

- **日期**：YYYY-MM-DD（多个用 ` / ` 分隔）
- **背景 / 现象**：发生了什么（决策类写"当时的背景"）
- **根因**：为什么会这样（决策类写"为什么这么定"）
- **结论**：怎么解决 / 最终决定是什么
- **实测**（可选）：关键数字 / 验证方式
- **位置**（可选）：涉及的文件 / 页面
```

**三种形态的选用**：

| 内容类型 | 形态 |
|---|---|
| 单条坑 / 决策 / 事实 | **字段块**（上面的模板） |
| 同质清单（多条结构相同的规则 / 调整 / 映射） | **表格** —— 列头即字段 |
| 操作规程（排查流程等） | **步骤结构**，不套字段块 |

---

## 一、2026-10-14 迁移：uni-app → 纯 Vue3 + Vite

#### 为什么迁（决策）

- **日期**：2026-10-14
- **背景 / 现象**：comic-front（uni-app 版）已 H5 单平台化（2026-10-13 移除小程序 / App 支持）——
  多端编译的价值归零，但 uni 的成本全留着：`uni-compat.css` 归一化层、模板白名单（无 `<select>` / `<table>`）、
  编译器坑（`@pointerdown` 被吞、`@click.self` 不可靠、`uni-input` type 白名单）、版本锁死（vite 卡 5.2.8）、
  运行时多 ~100KB。
- **根因**：uni-app 的核心价值是"一套代码多端编译"；单 H5 下它只剩"编译 + 运行时中间层"。
- **结论**：**以 comic-front 为蓝本 1:1 迁移到 comic-web（纯 Vue3 + Vite）**，页面 / 交互 / 接口全部对齐，
  只换技术栈。路由换成标准 vue-router（hash 模式）、守卫换路由级 `beforeEnter`（比页面内 await 更标准）。
- **实测**：主 chunk 265KB → **163KB**（省掉 uni 运行时）；生产构建 2.6s。

#### 迁移的「对照表」（uni 写法 → 纯 Web 写法）

| uni 时代 | 纯 Web 版 |
|---|---|
| `pages.json` + `uni.navigateTo/redirectTo` + 手写 router shim | **vue-router**（`router.ts`，15 页 + 守卫） |
| 页面内 `onLoad` + `setRoute` + `await requireRole` | `onMounted` + `useRoute().params/query` + **路由级 `beforeEnter`** |
| `onReachBottom(loadMore)`（页面级生命周期） | **`useReachBottom(loadMore)`**（scroll 监听 + 200ms 节流） |
| `onShow` / `onHide` / `onUnload` | `visibilitychange` / `onBeforeUnmount` |
| `uni.showModal` / `uni.showToast` / `uni.showLoading` | `utils/ui.ts`（原生 `<dialog>` + 动态 DOM） |
| `uni.request` | **axios**（`api/request.ts`，行为逐条对齐） |
| `uni.uploadFile`（头像） | `FormData` + axios；选图用动态 `<input type="file">` |
| `<swiper>` / `<switch>` / `<picker>` / `<image>` | 自绘轮播 / 自绘开关（项目既有 `.switch`）/ 原生 `<select>` / `<img>` |
| `router.back()`（跳固定上级 + replace） | **`parentOf()` + `router.replace`**（`utils/nav.ts`）——**别用 vue-router 的 `back()`**（依赖浏览历史） |

#### ⚠️ 三个迁移期的真坑（都已修）

- **`measureAll` 丢了 `dataset`（阅读器页号不联动）**：uni 的 `boundingClientRect` 回调对象**带 `dataset`**
  （调用方用 `b.dataset.page` 取页码）；换成原生 `getBoundingClientRect` 后必须**手动附上 `el.dataset`**，
  否则页号恒为 1（滚动测量静默失效）。
- **`form-type="submit"` / `@confirm` 是 uni 专有**：原生下按钮要 `type="submit"`、回车走 form 隐式提交
  （`@confirm` 改 `@keyup.enter` 或删掉）；⚠️ **`<form>` 必须写 `@submit.prevent`**，否则原生提交会刷新页面。
- **`password` 属性是 uni 专有**：原生要写 `type="password"`（`password` 会被忽略成明文输入框）。
