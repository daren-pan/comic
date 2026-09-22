# comic-front 前端（uni-app · Vue 3 + TypeScript + Vite + Pinia）

漫画聚合阅读平台的**多端前端**，由 `../comic-web`（纯 Web SPA）一比一移植而来：

- **业务约定与逻辑完全不变** —— 页面结构、接口调用、登录态、消息中心、阅读器行为都与 `comic-web` 一致；
- **只换底层设施** —— vue-router → uni 页面栈、axios → `uni.request`、`localStorage` → uni 存储、
  `window` 自定义事件 → `uni.$emit`；差异全部收敛在 `src/utils/` 与 `src/api/request.ts`，业务层不感知；
- **当前主用**；`comic-web` 保留为参考实现、不再改动。

## 目录结构

```
comic-front/
├── index.html                # H5 入口（uni 约定）
├── vite.config.ts            # vite + @dcloudio/vite-plugin-uni；/api 代理到 8000；dev 端口 5174
└── src/
    ├── main.ts               # createSSRApp 工厂（uni 约定），注入 Pinia + 全局样式
    ├── App.vue               # 应用级容器（uni 的 App.vue 不渲染页面）+ 小程序端 button 归一化
    ├── pages.json            # 路由表（替代 vue-router 的 route 定义）
    ├── manifest.json         # 各端打包配置（appid / h5 base 等）
    ├── style.css             # 全局设计变量与基础样式（与 comic-web 同源）
    ├── uni-compat.css        # uni 内置组件默认样式归一化（H5 侧，见下文）
    ├── types.ts              # 领域类型（与 comic-web 逐字一致）
    ├── api/                  # 与 comic-web 同构：request / auth / content / user / admin / ondemand
    ├── stores/               # Pinia：user（登录态）/ message（消息中心）
    ├── components/
    │   ├── Layout.vue        # 由 comic-web 的 App.vue 移植：顶栏 + 消息中心 + 页脚 + toast
    │   ├── ComicCard.vue · Picker.vue · DateInput.vue
    ├── utils/                # 兼容层（comic-front 特有，见下）
    │   ├── router.ts · storage.ts · event.ts · guard.ts · ui.ts
    └── pages/                # 每个页面一个目录（uni 约定），共 11 页
```

## 页面与路由（`src/pages.json`）

| uni 页面路径 | 对应 web 路由 | 页面 | 说明 |
|---|---|---|---|
| `pages/index/index` | `/` | 首页 | Banner + 热门榜单 + 最新更新 + 分类精选 |
| `pages/search/index` | `/search` | 分类浏览 / 搜索 | 关键词 + 分类 + 排序 + 分页；站内搜不到时**搜源站并导入** |
| `pages/latest/index` | `/latest` | 最近更新 | 卡片网格（`sort=updated`），带相对时间角标 |
| `pages/rank/index` | `/rank` | 排行 | 分类区块分批懒加载（首屏 4 个，触底追加）+ 块内热度前 10 |
| `pages/comic/index` | `/comic/:id` | 详情页 | 封面 / 简介 / 标签 / 来源标注 + 收藏 + 章节列表 + 续读 |
| `pages/reader/index` | `/reader/:comicId/:chapterId` | 在线阅读器 | 双阅读模式、主题切换、章节切换、进度记忆 |
| `pages/me/index` | `/me` | 我的 | 最近阅读（续读 / 删除）+ 我的收藏 |
| `pages/login/index` | `/login` | 登录 / 注册 | JWT 登录；收藏需登录，历史**登录后归属账号、游客用浏览器匿名 id** |
| `pages/admin/index` | `/admin` | 采集管理台 | 采集 / 巡检 / 封面自愈；**需管理员** |
| `pages/admin/logs` | `/admin/logs` | 运行日志查询 | 按级别 / 源站 / 事件 / 作品 / 时间窗筛；**需管理员** |
| `pages/admin/users` | `/admin/users` | 授权管理 | 普通管理员 ⇄ 普通用户；**仅超管** |

> 管理台三页**不做 H5 专属**，移动端同样可访问（顶栏入口按角色显示）。

顶栏由 `components/Layout.vue` 渲染：**每个页面都要用 `<Layout>` 包住自身内容** —— uni 没有全局路由出口，
所以 `comic-web/App.vue` 的 `<RouterView />` 换成了 `<slot />`。

## 模块架构

### 兼容层（`src/utils/`）—— 让页面代码不必改写法

| 模块 | 替代 | 说明 |
|---|---|---|
| `router.ts` | vue-router | 同形的 `useRoute()` / `useRouter()`；`toUniUrl()` 把 `/comic/3`、`{path,query}` 解析成 `pages/comic/index?id=3`；`openNewTab()` 在 H5 开新标签、其他端退化为同页跳转 |
| `storage.ts` | localStorage | `get/set/remove`，语义一致（读不到返回 `null`），底层 `uni.*StorageSync` |
| `event.ts` | `window` 自定义事件 | `emit/on/off` → `uni.$emit/$on/$off` |
| `guard.ts` | vue-router 的 `beforeEnter` | uni 页面栈没有路由钩子 → `requireRole(superOnly, fullPath)`，由三个管理台页面在 `onLoad` 里 `await` |
| `ui.ts` | `window.alert/confirm` | `showAlert` / `showConfirm`（内部 `uni.showModal`），小程序无 `window` |
| `api/request.ts` | axios | `uni.request` 单通道；`request<T>(path,{method,data,params})` 签名不变；错误文案仍取后端 `detail`/`message` |

**与 vue-router 的差异（页面里必须知道）**

1. **路由参数走 `onLoad(options)`** —— uni 没有 `route.params`；`route.path/query` 由页面在 `onLoad` 里调 `setRoute()` 登记。
2. **同页查询变更**（如搜索页切分类）：uni 不允许 `navigateTo` 自身 → `router.replace` 只做「本地状态 + H5 地址栏同步」。
3. **管理台门卫是「页面内调用」**：在 `onLoad` 里 `await requireRole(...)`，未通过则整页不渲染并跳登录页。
4. **H5 地址栏是 uni 自己的路径**：`#/pages/rank/index`、`#/pages/comic/index?id=43`（**不是** `#/rank`）——
   站内跳转由 `toUniUrl()` 转换，但**书签 / 外链要按 uni 这套路径写**。

**对 `comic-web` 的五处有意调整**（前三条是逻辑、后两条是视觉/控件）

| # | 位置 | 现状 | 原因 |
|---|---|---|---|
| 1 | `pages/reader` 的 `chapterId` | 由 `const` 改 `ref`，`goChapter()` 同步更新 | 原写法换章后不更新，上下章按钮与目录高亮会失真 |
| 2 | `pages/reader` 的参数 watcher | 删除 | `goChapter()` 本就显式 `loadChapter()`，避免重复加载 |
| 3 | `pages/search` 监听 `route.fullPath`（字符串） | 不再监听 `route.query` 对象 | 兼容层的 `query` 每次登记都是新对象，按引用比较会重复触发 |
| 4 | `pages/login` 返回按钮 | 移入卡片内左上角（内缩 16/14px）、绿色 `#15803d` | 用户指定的视觉调整；绿色就地取值，**未**新增调色板变量以保持 `style.css` 与 comic-web 同源 |
| 5 | 管理台日期控件（5 处） | 改用 `components/DateInput.vue`（H5 仍是原生 `<input type="date">`，其它端降级为文本输入） | uni 的 `<input>` **不支持 `type="date"`**（白名单外会被抹成 `text`） |

### uni 内置组件样式归一化（`src/uni-compat.css`）

comic-web 的样式表是按**原生** `input` / `button` / `form` 写的；搬到 uni 后被编译成**内置组件**
（`uni-input` / `uni-button` / `uni-form`），组件**自带默认样式 + 一层多余结构**，于是「CSS 一字未改却错位」。
这份文件只做一件事：**把 uni 组件归一化回原生元素的盒子模型**（不改业务、不改模板结构）。

| # | uni 的默认行为 | 归一化 |
|---|---|---|
| ① | `uni-form` 在子元素外**再包一层 `<span>`** | `uni-form > span { display: contents }`（否则 flex 从未生效） |
| ② | `uni-button` 默认 `display: block` | `display: inline-flex`（否则按钮占满整行） |
| ③ | `uni-button` 用 `line-height: 2.5555` **近似**垂直居中 | `align-items/justify-content: center`（业务一改 line-height 文字就贴顶） |
| ④ | `uni-button` 默认 `margin-left/right: auto` | `margin: 0`（否则 flex 行里被吸到两端） |
| ⑤ | `uni-button` 默认 `padding: 0 14px`、`font-size: 18px` | 还原原生 `1px 6px` / `13.3333px` |
| ⑥ | `uni-button` 默认 `overflow: hidden` | `overflow: visible`（否则未读红点被裁掉） |
| ⑦ | `uni-button` 用 `::after` 画 1px 边框 | `html uni-button::after { border: none }` |
| ⑧ | `uni-input` 写死 `height: 1.4em` + `box-sizing: border-box`，内层又 `height: 100%` | `height: auto; min-height: 0` + 内层 `height: auto`（否则只给 padding 时**输入框高 0px、点不进去**） |
| ⑨ | `uni-input` 默认 `line-height: 1.4em` | `line-height: normal` |
| ⑩ | uni 组件**继承 body 字体栈** | `html uni-button, html uni-input { font-family: Arial }`（原生表单控件不继承页面字体，行盒高度不同会差 3px） |
| ⑪ | `uni-label` 有子内容就挂 `.uni-label-pointer` | `html uni-label.uni-label-pointer { cursor: default }`（否则说明文字出现小手） |

> 小程序端 uni 不注入这层 `<span>`、也不注入 H5 那套组件 CSS，所以本文件在那些端**自然空转** ——
> 属于 H5 专属适配，但不是 H5 专属代码。

## 多端适配

H5 与小程序（mp-weixin）共用同一份源码，靠**条件编译 + 只用跨端 API**实现。

| 原标签 → 现在 | 说明 |
|---|---|
| `div/section/header/nav/ul/li/p/h1-h4/table 系` → `view` | 块级 |
| `span/b/em/small/code` → `text`；**`label` → `view`** | `label` 是 flex 容器，且 `<text>` 内不能放表单组件 |
| `a` → **`view`** | 卡片外层 `a` 包着 `view`/`image`，**不能**映射成 `text`（小程序禁止 `<text>` 内放块级组件） |
| `img` → `image` | 补 `mode="aspectFill"`（等价 `object-fit: cover`） |
| `select/option` → `components/Picker.vue` | 小程序无 select；内部用 `<picker mode="selector">` |
| `input[type=checkbox]` → `switch` | uni 的 Input 对 `type` 有白名单 |
| `br` → `<view class="u-br">` | 空块级元素顶出换行 |

| H5 专属 API → 跨端等价物 | 影响面 |
|---|---|
| `PointerEvent` → 保留 pointer（H5 桌面拖拽）**+ 新增 touch**，靠 `active` 守卫去重 | 阅读器滑动翻页 |
| `requestAnimationFrame` → `setTimeout` 节流 | 竖排连播的当前页推导 |
| `element.scrollTo` → `scroll-view` 的 `scroll-into-view` | 阅读器跳页 / 切章 |
| `getBoundingClientRect` → `uni.createSelectorQuery().boundingClientRect` | 当前页推导、进度条跳页 |
| `overflow-y:auto` → `<scroll-view scroll-y>` | 阅读器竖排连播（小程序里普通 view 不能滚） |
| `IntersectionObserver` → `onReachBottom` + 分批渲染 | 排行页懒加载 |
| `e.clientX` → `eventX()`（H5 取 `clientX`、小程序取 `detail.x`） | 点击热区、进度条 |
| `@click.self` → `onMaskTap()`（比较 `target` 与 `currentTarget`） | 阅读器两个弹层 |
| `<transition>` → CSS `@keyframes` | 消息面板 / toast / 弹层（小程序不支持 transition 组件） |
| `window.alert/confirm` → `utils/ui.ts` | 日志页清理确认 |
| `document` 点击关面板 → 保留 H5 分支 + `#ifndef H5` 透明遮罩 | 顶栏消息中心 |
| `aspect-ratio` → padding-bottom 比例盒 / 写死高度 | 卡片、书架、缩略图 |
| `inset: 0` → 显式四边偏移 | 阅读器根元素（`inset` 需 Chrome 87+） |
| `button` 默认样式 → `App.vue` 的 `<style>`（`#ifdef MP-WEIXIN`） | 全站按钮 |

## 基础命令

前置：后端 8000 已在运行。接口统一相对路径 `/api/*`，由 Vite proxy 转发到 `127.0.0.1:8000`。

```bash
npm install
npm run dev:h5          # H5 开发 http://localhost:5174（HMR）
npm run build:h5        # H5 生产构建 → dist/build/h5
npm run dev:mp-weixin   # 微信小程序开发（产物 dist/dev/mp-weixin，用微信开发者工具打开）
npm run build:mp-weixin # 微信小程序构建
npm run dev:app         # App（需 HBuilderX 配合打包）
```

| 依赖 | 用途 | 备注 |
|---|---|---|
| `@dcloudio/*` | uni-app 运行时与编译 | **必须锁 `3.0.0-5020620260917001`**（vue3 线）；`latest` 会拉到 Vue2 线，报 `@vue/composition-api` 的 ERESOLVE |
| `@dcloudio/types` | 类型声明 | 锁 **`3.4.31`**（同上，`latest` 落在 Vue2 线） |
| vue 3 | 框架 | 与 comic-web 同版本线 |
| **pinia** | 登录态 / 消息中心全局共享 | 与 comic-web 一致用 pinia@2 |
| `@dcloudio/vite-plugin-uni` | 构建插件 | 其 peer 要求 **vite 5.2.8**（精确版本），已锁 |

## 约定

**多端红线（违反即在小程序端整块渲染不出来）**

- **不要用 HTML 标签**：模板只用 `view` / `text` / `image` / `button` / `input` / `textarea` / `form`，
  外加 `components/Picker.vue`（下拉）、`components/DateInput.vue`（日期）。
  `div`/`span`/`p`/`a`/`img`/`select`/`table` 在**小程序端整块渲染不出来**。
- **CSS 只写类选择器**：不要写 `view {}` / `.card a {}` 这类元素选择器 —— uni 在 H5 下渲染成
  `uni-view`/`uni-text`，元素选择器能否命中取决于编译器改写；需要时用 `u-<原标签>` 工具类。
- **不要绕过兼容层**：禁止直接 `import` vue-router、直接用 `localStorage`、用 `window.dispatchEvent`
  —— 一律走 `utils/router`、`utils/storage`、`utils/event`、`utils/ui`。
- **自定义组件上禁止 `v-model`**：小程序端编译器直接报错
  （`v-model can only be used on <input>, <textarea> and <select> elements`），
  一律写 `:model-value` + `@update:model-value`。
- **条件编译 `#ifdef` 只在 uni 会预处理的文件里生效**：`.vue` 的 `<style>` 算，**独立 `.css` 文件不算**
  （标记会被当普通注释压掉 → 规则两端都生效）。小程序专属样式请写进 `App.vue` 的 `<style>`，
  **改完两个产物都要反查**。
- **静态资源放 `src/static/`**（uni 约定，**不是** `public/`）。
- ⚠️ **uni 预处理会留 `.tmpdir` 临时目录**：编辑项目内文件时（`src/*.css`、根 `README.md` 都触发过）
  它会在旁边建 `<文件名>.<pid>.<uuid>.tmpdir/`，进程被中断则残留 —— 残留会让 Vite watcher 报 `EBUSY`
  并**直接崩掉 dev server**。删掉残留再重启即可（`comic-front/**/*.tmpdir`）。

**uni 语义（写表单 / 样式前先看）**

- **表单提交用 uni 语义**：按钮必须写 **`form-type="submit"`**（写 `type="submit"` 是死按钮）；
  `@submit` **不要加 `.prevent`**；回车提交监听 **`@confirm`**（没有原生表单的隐式回车提交）。
- **归一化规则的选择器要带 `html` 前缀**：uni 的组件样式是运行时 `insertRule` 注入、且**排在后面**，
  同权重会被它压过。`html uni-button` = 0,0,2 才压得住；但**压不住类选择器** ——
  遇到 `.uni-label-pointer` 这类要连类名一起写（`html uni-label.uni-label-pointer` = 0,1,2）。**改前先算权重。**
- **业务 CSS 权重更高**：归一化只兜底**没写**的属性（= 原生 UA 默认值），业务显式写过的照旧生效。
- **`uni-input` 的 `type` 是白名单**（text / number / idcard / digit / password / tel），
  白名单外一律被抹成 `text` —— 所以 `type="date"` 必须走 `DateInput.vue`。
- `DateInput` **不带样式**，靠根元素的 `class="date-inp"` 钩子让页面挂样式（uni 会把 scoped 的 `input` 改写成
  `uni-input`，匹配不到这个原生 input）。

**已知残留风险**（详细取舍见 `.workbuddy/memory/2026-09-22.md`）

- `flex gap`（69 处）需 Chrome 84+ / iOS 14.1+：老系统上间距会丢失，**布局不会错乱**。
- `backdrop-filter` 2 处属纯装饰；`min/max/clamp`、CSS `grid`、`sticky` 基线较老，风险低。
- **小程序端尚未在真机 / 微信开发者工具里跑过**（本机无 `appid`）；`manifest.json` 的 `appid` 待填。

---

> 修复过程与验证记录写在 `.workbuddy/memory/YYYY-MM-DD.md`，不进本文件。
