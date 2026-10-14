# comic-web 前端（纯 Vue 3 + Vite + TypeScript + Pinia）

漫画聚合平台的 **Web SPA**：数据来自 `../api-service` 的 REST API，内容由 `../crawler-service` 采集入库。

- **与 comic-front 功能等价**：页面、交互、接口调用、视觉全部对齐（`comic-front` 是同一份前端的
  uni-app 实现，两者是"孪生"关系；2026-10-14 由前者 1:1 迁移而来，只把技术栈换成纯 Vue3 + Vite）；
- **移动端为基准，网页版是增量**（2026-10-10 起双形态）：网页版全部写成 `.mode-web` 前缀的增量覆盖，
  按 UA 自动判定。网页版是**全新设计**、不参照旧版；
- 路由用标准 **vue-router**（hash 模式，构建产物可离线双击打开）；管理台守卫用**路由级
  `beforeEnter`**（`router.ts` 的 `requireRole`）。

> **文档分工**：本文件 = 模块框架 / 页面用途 / 约定 / 命令（给人看）；
> **[NOTES.md](NOTES.md) = 踩坑 / 实测 / 历史决策**（AI 协作时维护，踩坑即写）；
> **各页面的具体逻辑**由其源码注释解释维护。

## 目录结构

```
comic-web/
├── index.html                # 入口（含 favicon 随季节切换的内联脚本）
├── vite.config.ts            # vite + @vitejs/plugin-vue；/api 代理到 8000；dev 端口 5173
├── eslint.config.mjs         # ESLint（两条禁令：裸 alert / localStorage）
├── vitest.config.ts          # 单测配置（独立于 vite.config）
├── tests/                    # vitest：nav 映射 / 季节 / 分页状态机 / 约定守卫
├── public/static/logo/       # 四季站标 + favicon（季节切换见 utils/season.ts）
└── src/
    ├── main.ts               # createApp + Pinia + router
    ├── App.vue               # 只挂 <RouterView />（全站布局由各页用 <Layout> 自包）
    ├── router.ts             # 路由表（15 页）+ 管理台守卫（requireRole 三道门）
    ├── style.css             # 全局设计变量与工具类（含夜间主题变量组）
    ├── types.ts              # 领域类型（核心类型从后端 OpenAPI 自动生成提取）
    ├── api/                  # request 单通道 + 业务模块；generated/ 为自动生成（勿手改）
    ├── composables/          # 页面共享模式（usePagedList：分页/竞态/失败回退；useReachBottom）
    ├── stores/               # Pinia：user（登录态）/ message（消息中心）
    ├── components/           # Layout / ComicCard / Pager / StateView / FilterBar / Picker / DateInput / AdminTabs / UserAvatar
    ├── utils/                # 适配层：storage / event / ui / theme / layout / nav / format / season / icons
    └── views/                # 15 个页面（每页一个文件）
```

## 页面与路由（`src/router.ts`）

| 路由 | 页面 | 说明 |
|---|---|---|
| `/` | 首页 | 顶栏（站标 + 轮播播报）+ 热门榜单 + 最新更新 + 分类精选 |
| `/search` | 分类浏览 / 搜索 | 关键词 + `FilterBar` + 分页（18/页）；站内搜不到时**搜源站并导入** |
| `/latest` | 最近更新 | 按日期分组（组头吸顶）+ 触底自动追加 |
| `/rank` | 排行 | 全库榜单（默认热度降序）+ `FilterBar`；触底追加 |
| `/comic/:id` | 详情页 | 封面 / 简介 / 标签 + 收藏 + 章节列表（NEW 角标 + 正倒序）+ 评论区 + 续读 |
| `/reader/:comicId/:chapterId` | 在线阅读器 | 双阅读模式、主题切换、章节切换、进度记忆 |
| `/me` | 我的（书架） | 最近阅读（续读 / 删除）+ 我的收藏 |
| `/profile` | 个人中心 | 资料（头像 / 昵称可点即改）+ 修改密码 + 退出登录 |
| `/messages` | 消息中心 | 服务端 `message` 表、所有登录用户（按收件范围过滤）；**顶栏铃铛的落点** |
| `/login` | 登录 / 注册 | JWT；收藏需登录，历史游客用浏览器匿名 id |
| `/admin` | 采集管理台 | 采集 / 巡检 / 封面自愈；**需管理员** |
| `/admin/comics` | 作品管理 | 上下架 + 评论开关（全站 + 单作品）+ 补全章节；**搜索式**（不列全部）；**需管理员** |
| `/admin/schedule` | 定时任务配置 | cron + 动作 + 运行状态（执行器在线 / 下次执行）；**需管理员** |
| `/admin/logs` | 运行日志查询 | 按级别 / 源站 / 事件 / 作品 / 任务 / 时间窗筛；**需管理员** |
| `/admin/users` | 授权管理 | 普通管理员 ⇄ 普通用户；**仅超管** |

> 管理台四个页面顶部是**同一栏的四个选项卡**（`components/AdminTabs.vue`，导航式 —— 各页仍是独立路由，
> 可直达可分享）；「作品管理」只进选项卡栏、不进抽屉菜单。
> **每个页面都要用 `<Layout>` 包住自身内容**（与 comic-front 结构一致，页面代码因此零改动迁移）。

## 模块架构

### 适配层（`src/utils/`）

| 模块 | 说明 |
|---|---|
| `nav.ts` | `parentOf()`（层级返回的固定上级树）+ `openNewTab()`；**顶栏返回键不依赖浏览历史** |
| `storage.ts` | `get/set/remove`，语义与 localStorage 一致（读不到返回 `null`） |
| `event.ts` | `emit/on/off` → `window` 自定义事件（登录态变更广播） |
| `ui.ts` | `showAlert` / `showConfirm` / `showToast` / `showLoading`（基于原生 `<dialog>` 与动态 DOM，全站唯一弹窗出口） |
| `theme.ts` | `useTheme()` → `{ theme, isDark, setTheme, toggleTheme }`；选择存本地、未选过时跟随系统 |
| `layout.ts` | `useLayoutMode()` → `{ mode, isWebMode }`；**只按 UA 判定**（手机 → 移动版 / 电脑 → 网页版） |
| `format.ts` | 时间格式化：`formatDateTime` / `formatMonthDay` / `formatCommentTime` / `formatInterval` / `formatHeat` |
| `season.ts` | 季节判定 + 四季站标资源（`public/static/logo/`） |
| `icons.ts` | 底栏图标（自绘 SVG → base64 data URI，明暗两套） |

### 后端契约与类型生成

`src/types.ts` 的核心类型（`Comic` / `AdminComic` / `Chapter` / `PageInfo` / `Comment`）**从后端 OpenAPI 自动生成提取**，
不再手抄。后端改字段后重跑两步即可让前端类型跟上：

```bash
# ① 后端侧：导出契约快照（in-process，不要求服务在跑）
python tools/export_openapi.py        # → api-service/openapi.json
# ② 前端侧：生成 TS 类型
cd comic-web && npm run gen:api       # → src/api/generated/schema.d.ts
```

## 基础命令

前置：后端 8000 已在运行。接口统一相对路径 `/api/*`，由 Vite proxy 转发到 `127.0.0.1:8000`。

```bash
npm install
npm run dev             # 开发 http://localhost:5173（HMR）
npm run build           # 生产构建 → dist/
npm run lint            # ESLint（禁裸 alert / localStorage）
npm run test            # vitest（nav 映射 / 季节 / 分页状态机 / 约定守卫）
npm run typecheck       # tsc --noEmit（.ts 类型检查）
npm run check           # lint + typecheck + test
npm run gen:api         # 从后端 OpenAPI 快照生成类型（见上「后端契约与类型生成」）
```

| 依赖 | 用途 | 备注 |
|---|---|---|
| vue 3 + **vue-router** + **pinia** | 框架 / 路由 / 全局共享 | 标准生态，无额外运行时抽象 |
| **axios** | 请求 | 单通道封装在 `api/request.ts` |
| `vite` 5 + `@vitejs/plugin-vue` | 构建 | `base: './'`，产物可挂任意子路径 |
| eslint 9 / vitest 3 / openapi-typescript 7 | 门禁 / 单测 / 类型生成 | 版本兼容约束见 [NOTES.md](NOTES.md) |

## 约定

**写法约定（全站统一；机器门禁 = ESLint + `tests/conventions.test.ts`）**

- **模板只用原生标签 + 自建组件**：原生 `div` / `span` / `img` / `button` / `input` / `select` / `textarea` / `form`
  （uni 时代的"只能用 uni 组件"约束已随迁移取消），外加 `components/` 下的自建组件。
  ⚠️ 自建组件**必须 import**：漏了 import 时 Vue 只把它当未知标签、**控制台报警且渲染为空**。
- **CSS 只写类选择器**：不要写 `div {}` / `.card span {}` 这类元素选择器；需要时用 `u-<原标签>` 工具类。
- **不要绕过适配层**：禁止裸 `alert` / `confirm`、直接 `localStorage` —— 一律走 `utils/ui`、`utils/storage`
  （ESLint 机器门禁）；返回上层一律用 `utils/nav` 的 `parentOf`（**别用 `router.back()`**，它依赖浏览历史）。
- **自定义组件上不写 `v-model`**：统一用 `:model-value` + `@update:model-value` 显式写法
  （`tests/conventions.test.ts` 有守卫）。
- **表单用原生语义**：`<form @submit.prevent="...">` + `<button type="submit">`（回车走隐式提交）；
  不在 form 里的输入框回车用 `@keyup.enter`。**`.prevent` 不能省**（原生表单提交会刷新页面）。
- **页面取数走 `composables/usePagedList`**（分页 / 竞态 / 失败回退 / 三态）、触底加载走 `useReachBottom`：
  不要在页面里手写 `reqId` 令牌与页码回退。
- **表面色一律走 CSS 变量，禁止再写 `#fff`**：主题（明亮 / 夜间）就是换一套变量值，写死的白底在夜间
  会变成「白底 + 浅字」。变量分工见 `style.css` 注释。
