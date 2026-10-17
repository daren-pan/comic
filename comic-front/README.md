# comic-front 前端（uni-app · Vue 3 + TypeScript + Vite + Pinia）

漫画聚合阅读平台的前端（uni-app），由 `../comic-web`（纯 Web SPA）一比一移植而来：

- **业务约定与逻辑完全不变** —— 页面结构、接口调用、登录态、消息中心、阅读器行为都与 `comic-web` 一致；
  平台差异全部收敛在 `src/utils/`（兼容层）与 `src/api/request.ts`，业务层不感知；
  （对 comic-web 的**有意调整**逐条记录在 [NOTES.md](NOTES.md) §1.1）
- **移动端为基准，网页版是增量**（2026-10-10 起双形态）：网页版全部写成 `.mode-web` 前缀的增量覆盖，
  按 UA 自动判定。网页版是**全新设计**、不参照 `comic-web`；
- ⚠️ **目标平台 = H5**（移动端 + 网页端两种形态）；构建目标只有 `build:h5` 一个；
- comic-web 曾长期作为本端的参考实现；2026-10-14 已以本端为蓝本重写为纯 Vue3 版，现与本端功能等价、独立维护（两个镜像各自带 nginx）。

> **文档分工**：本文件 = 模块框架 / 页面用途 / 约定 / 命令（给人看）；
> **[NOTES.md](NOTES.md) = 踩坑 / 实测 / 历史决策 / 排查规程**（AI 协作时维护，踩坑即写）；
> **各页面的具体逻辑**由其源码注释解释维护。

## 目录结构

```
comic-front/
├── index.html                # H5 入口（uni 约定）
├── vite.config.ts            # vite + @dcloudio/vite-plugin-uni；/api 代理到 8000；dev 端口 5174
├── eslint.config.mjs         # ESLint（三条禁令：裸 alert / localStorage / uni.request）
├── vitest.config.ts          # 单测配置（独立于 vite.config，避免加载 uni 插件）
├── tests/                    # vitest：路由映射 / 季节 / 分页状态机 / 约定守卫
└── src/
    ├── main.ts               # createSSRApp 工厂（uni 约定），注入 Pinia + 全局样式
    ├── App.vue               # 应用级容器（uni 的 App.vue 不渲染页面）
    ├── pages.json            # 路由表（替代 vue-router 的 route 定义）
    ├── manifest.json         # 应用配置（h5 标题 / router base 等）
    ├── style.css             # 全局设计变量与基础样式（与 comic-web 同源）
    ├── uni-compat.css        # uni 内置组件默认样式归一化（见 NOTES §2.1）
    ├── types.ts              # 领域类型（核心类型从后端 OpenAPI 自动生成提取，见下）
    ├── api/                  # request 单通道 + 业务模块；generated/ 为自动生成（勿手改）
    ├── composables/          # 页面共享模式（usePagedList：分页/竞态/失败回退）
    ├── stores/               # Pinia：user（登录态）/ message（消息中心）
    ├── components/           # Layout（全站壳）/ ComicCard / Pager / StateView / FilterBar / Picker / DateInput / AdminTabs / UserAvatar
    ├── utils/                # 兼容层（本端特有）+ format.ts（全站时间格式化，8 处收敛为 1 份）
    └── pages/                # 每个页面一个目录（uni 约定），共 15 页
```

## 页面与路由（`src/pages.json`）

| uni 页面路径 | 对应 web 路由 | 页面 | 说明 |
|---|---|---|---|
| `pages/index/index` | `/` | 首页 | 顶栏（站标 + 轮播播报）+ 热门榜单 + 最新更新 + 分类精选 |
| `pages/search/index` | `/search` | 分类浏览 / 搜索 | 关键词 + `FilterBar` + 分页（18/页）；站内搜不到时**搜源站并导入** |
| `pages/latest/index` | `/latest` | 最近更新 | 按日期分组（组头吸顶）+ 触底自动追加 |
| `pages/rank/index` | `/rank` | 排行 | 全库榜单（默认热度降序）+ `FilterBar`；触底追加 |
| `pages/comic/index` | `/comic/:id` | 详情页 | 封面 / 简介 / 标签 + 收藏 + 章节列表（NEW 角标 + 正倒序）+ 评论区 + 续读 |
| `pages/reader/index` | `/reader/:comicId/:chapterId` | 在线阅读器 | 双阅读模式、主题切换、章节切换、进度记忆 |
| `pages/me/index` | `/me` | 我的（书架） | 最近阅读（续读 / 删除）+ 我的收藏 |
| `pages/profile/index` | `/profile` | 个人中心 | 资料（头像 / 昵称可点即改）+ 修改密码 + 退出登录 |
| `pages/messages/index` | `/messages` | 消息中心 | 服务端 `message` 表、所有登录用户（按收件范围过滤）；**顶栏铃铛的落点** |
| `pages/login/index` | `/login` | 登录 / 注册 | JWT；收藏需登录，历史游客用浏览器匿名 id |
| `pages/admin/index` | `/admin` | 采集管理台 | 采集 / 巡检 / 封面自愈；**需管理员** |
| `pages/admin/comics` | `/admin/comics` | 作品管理 | 上下架 + 评论开关（全站 + 单作品）+ 补全章节；**搜索式**（不列全部）；**需管理员** |
| `pages/admin/schedule` | `/admin/schedule` | 定时任务配置 | cron + 动作 + 运行状态（执行器在线 / 下次执行）；**需管理员** |
| `pages/admin/logs` | `/admin/logs` | 运行日志查询 | 按级别 / 源站 / 事件 / 作品 / 任务 / 时间窗筛；**需管理员** |
| `pages/admin/users` | `/admin/users` | 授权管理 | 普通管理员 ⇄ 普通用户；**仅超管** |

> 管理台四个页面顶部是**同一栏的四个选项卡**（`components/AdminTabs.vue`，导航式 —— 各页仍是独立路由，
> 可直达可分享）；「作品管理」只进选项卡栏、不进抽屉菜单。
> **每个页面都要用 `<Layout>` 包住自身内容** —— uni 没有全局路由出口，
> 所以 `comic-web/App.vue` 的 `<RouterView />` 换成了 `<slot />`。

## 模块架构

### 兼容层（`src/utils/`）—— 让页面代码不必改写法

| 模块 | 替代 | 说明 |
|---|---|---|
| `router.ts` | vue-router | 同形的 `useRoute()` / `useRouter()`；`toUniUrl()` 把 `/comic/3`、`{path,query}` 解析成 `pages/comic/index?id=3`；`openNewTab()` 开新标签 |
| `storage.ts` | localStorage | `get/set/remove`，语义一致（读不到返回 `null`），底层 `uni.*StorageSync` |
| `theme.ts` | 主题管理器 | `useTheme()` → `{ theme, isDark, setTheme, toggleTheme }`；选择存本地、未选过时跟随系统 |
| `layout.ts` | 布局模式管理器 | `useLayoutMode()` → `{ mode, isWebMode }`；**只按 UA 判定**（手机 → 移动版 / 电脑 → 网页版） |
| `event.ts` | `window` 自定义事件 | `emit/on/off` → `uni.$emit/$on/$off` |
| `guard.ts` | vue-router 的 `beforeEnter` | uni 页面栈没有路由钩子 → `requireRole(superOnly, fullPath)`，由管理台页面在 `onLoad` 里 `await` |
| `ui.ts` | `window.alert/confirm` | `showAlert` / `showConfirm`（内部 `uni.showModal`，全站统一弹窗出口） |
| `format.ts` | 时间格式化 | `formatDateTime` / `formatMonthDay` / `formatCommentTime` / `formatInterval` / `formatHeat` 等 |
| `api/request.ts` | axios | `uni.request` 单通道；`request<T>(path,{method,data,params})` 签名不变；错误文案仍取后端 `detail`/`message` |

### 与 vue-router 的差异（页面里必须知道）

1. **路由参数走 `onLoad(options)`** —— uni 没有 `route.params`；`route.path/query` 由页面在 `onLoad` 里调 `setRoute()` 登记。
2. **同页查询变更**（如搜索页切分类）：uni 不允许 `navigateTo` 自身 → `router.replace` 只做「本地状态 + 地址栏同步」。
   ⚠️ 这种写法**只给 `query`、不给 `path`**（`router.replace({ query: {...} })`），`toUniUrl()` 会补当前路径
   （`to.path || route.path`）。**别把这个兜底删掉** —— 缺了它 path 是 `undefined`，会抛
   `TypeError: Cannot read properties of undefined`，并打断调用方后续语句（表现为"点分类标签只切高亮、不查数据"）。
3. **管理台门卫是「页面内调用」**：在 `onLoad` 里 `await requireRole(...)`，未通过则整页不渲染并跳登录页。
4. **H5 地址栏是 uni 自己的路径**：`#/pages/rank/index`、`#/pages/comic/index?id=43`（**不是** `#/rank`）——
   站内跳转由 `toUniUrl()` 转换，但**书签 / 外链要按 uni 这套路径写**。

### 后端契约与类型生成

`src/types.ts` 的核心类型（`Comic` / `AdminComic` / `Chapter` / `PageInfo` / `Comment`）**从后端 OpenAPI 自动生成提取**，
不再手抄。后端改字段后重跑两步即可让前端类型跟上：

```bash
# ① 后端侧：导出契约快照（in-process，不要求服务在跑）
python tools/export_openapi.py        # → api-service/openapi.json
# ② 前端侧：生成 TS 类型
cd comic-front && npm run gen:api     # → src/api/generated/schema.d.ts
```

### uni 内置组件样式归一化（`src/uni-compat.css`）

把 uni 内置组件（`uni-input` / `uni-button` / `uni-form`…）的默认样式**归一化回原生元素的盒子模型**
（11 条规则逐条记录在 [NOTES.md](NOTES.md) §2.1）。改这个文件前先读那边的注释。

## 基础命令

前置：后端 8000 已在运行。接口统一相对路径 `/api/*`，由 Vite proxy 转发到 `127.0.0.1:8000`。

```bash
npm install
npm run dev:h5          # H5 开发 http://localhost:5174（HMR）
npm run build:h5        # H5 生产构建 → dist/build/h5
npm run lint            # ESLint（禁裸 alert / localStorage / uni.request）
npm run test            # vitest（路由映射 / 季节 / 分页状态机 / 约定守卫）
npm run typecheck       # tsc --noEmit（.ts 类型检查）
npm run check           # lint + typecheck + test
npm run gen:api         # 从后端 OpenAPI 快照生成类型（见上「后端契约与类型生成」）
```

| 依赖 | 用途 | 备注 |
|---|---|---|
| `@dcloudio/*` | uni-app 运行时与编译 | **必须锁 `3.0.0-5020620260917001`**（vue3 线）；`latest` 会拉到 Vue2 线，报 ERESOLVE |
| `@dcloudio/types` | 类型声明 | 锁 **`3.4.31`**（同上） |
| vue 3 + **pinia** | 框架 / 全局共享 | 与 comic-web 同版本线（pinia@2） |
| `vite` 5.2.8 | 构建 | 插件 peer 是**精确版本**，已锁 |
| eslint 9 / vitest 3 / openapi-typescript 7 | 门禁 / 单测 / 类型生成 | 版本兼容约束见 [NOTES.md](NOTES.md) §5.3 |

## 约定

**写法约定（全站统一；机器门禁 = ESLint + `tests/conventions.test.ts`）**

- **模板只用 uni 组件**：`view` / `text` / `image` / `button` / `input` / `textarea` / `form`，
  外加 `components/Picker.vue`（下拉）、`components/DateInput.vue`（日期）、
  `components/AdminTabs.vue`（管理台选项卡）、`components/Pager.vue`（分页条）。
  （全站既有写法：布局、事件、样式归一都按 uni 组件体系组织。）
  ⚠️ 自建组件**必须 import**：漏了 import 时 uni 只把它当未知标签、**静默渲染成空**（不报错）。
- **CSS 只写类选择器**：不要写 `view {}` / `.card a {}` 这类元素选择器 —— uni 下渲染成
  `uni-view`/`uni-text`，元素选择器能否命中取决于编译器改写；需要时用 `u-<原标签>` 工具类。
- **不要绕过兼容层**：禁止直接 `import` vue-router、直接用 `localStorage`、用 `window.dispatchEvent`、
  裸 `alert` / `confirm` —— 一律走 `utils/router`、`utils/storage`、`utils/event`、`utils/ui`（ESLint 机器门禁）。
- **自定义组件上不写 `v-model`**：统一用 `:model-value` + `@update:model-value` 显式写法
  （`tests/conventions.test.ts` 有守卫）。
- **静态资源放 `src/static/`**（uni 约定，**不是** `public/`）。
- **页面取数走 `composables/usePagedList`**（分页 / 竞态 / 失败回退 / 三态）：不要在页面里手写
  `reqId` 令牌与页码回退 —— 那段逻辑此前在 5 个页面逐字重复，踩过的坑都封在 composable 里。

**uni 语义（写表单 / 样式前先看）**

- **表单提交用 uni 语义**：按钮必须写 **`form-type="submit"`**（写 `type="submit"` 是死按钮）；
  `@submit` **不要加 `.prevent`**；回车提交监听 **`@confirm`**（没有原生表单的隐式回车提交）。
- **归一化规则的选择器要带 `html` 前缀**：uni 的组件样式是运行时 `insertRule` 注入、且**排在后面**，
  同权重会被它压过。`html uni-button` = 0,0,2 才压得住；但**压不住类选择器** ——
  遇到 `.uni-label-pointer` 这类要连类名一起写（`html uni-label.uni-label-pointer` = 0,1,2）。**改前先算权重。**
- **业务 CSS 权重更高**：归一化只兜底**没写**的属性（= 原生 UA 默认值），业务显式写过的照旧生效。
- **`uni-input` 的 `type` 是白名单**（text / number / idcard / digit / password / tel），
  白名单外一律被抹成 `text` —— 所以 `type="date"` 必须走 `DateInput.vue`。
- **表面色一律走 CSS 变量，禁止再写 `#fff`**：主题（明亮 / 夜间）就是换一套变量值，写死的白底在夜间
  会变成「白底 + 浅字」。变量分工表见 [NOTES.md](NOTES.md) §3.3。
