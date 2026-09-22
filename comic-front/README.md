# comic-front 前端（uni-app · Vue 3 + TypeScript + Vite + Pinia）

漫画聚合阅读平台的**多端前端**，由 `../comic-web`（纯 Web SPA）**一比一移植**而来：

- **业务约定与逻辑完全不变** —— 页面结构、接口调用、登录态、消息中心、阅读器行为都与 `comic-web` 一致；
- **只换底层设施** —— vue-router → uni 页面栈、axios → `uni.request`、`localStorage` → `uni` 存储、
  `window` 自定义事件 → `uni.$emit`；这些差异全部收敛在 `src/utils/` 与 `src/api/request.ts`，业务层不感知；
- **当前优先保证 H5 双端（桌面 + 手机）跑通**；小程序 / App 的落地清单见文末「多端待办」。

> `comic-web` 仍在仓库里、不做任何改动；本目录是它的 uni-app 并行版本。

## 目录结构

```
comic-front/
├── index.html                # H5 入口（uni 约定）
├── vite.config.ts            # vite + @dcloudio/vite-plugin-uni；/api 代理到 127.0.0.1:8000；dev 端口 5174
├── tsconfig.json
└── src/
    ├── main.ts               # createSSRApp 工厂（uni 约定），注入 Pinia + 全局样式
    ├── App.vue               # 应用级容器（uni 的 App.vue 不渲染页面）
    ├── pages.json            # 路由表（替代 vue-router 的 route 定义）
    ├── manifest.json         # 各端打包配置（appid / h5 base 等）
    ├── style.css             # 全局设计变量与基础样式（与 comic-web 同源）
    ├── uni-compat.css        # ★ uni 内置组件（button/input/form）默认样式归一化（见下文专节）
    ├── types.ts              # 领域类型（与 comic-web 逐字一致）
    ├── env.d.ts
    ├── api/                  # 与 comic-web 同构：request / auth / content / user / admin / ondemand
    ├── stores/               # Pinia：user（登录态）/ message（消息中心）
    ├── components/
    │   ├── Layout.vue        # 由 comic-web 的 App.vue 移植：顶栏 + 消息中心 + 页脚 + toast
    │   └── ComicCard.vue
    ├── utils/                # ★ 兼容层（comic-front 特有）
    │   ├── router.ts         # 同形 useRoute/useRouter + setRoute + openNewTab
    │   ├── storage.ts        # localStorage 同语义封装（uni 存储）
    │   ├── event.ts          # 全局事件总线（uni.$emit/$on/$off）
    │   └── guard.ts          # 管理台门卫 requireRole（替代 vue-router 的 beforeEnter）
    └── pages/                # 每个页面一个目录（uni 约定）
        ├── index/index.vue   ├── search/index.vue  ├── latest/index.vue
        ├── rank/index.vue    ├── comic/index.vue   ├── reader/index.vue
        ├── me/index.vue      ├── login/index.vue
        └── admin/index.vue · admin/logs.vue · admin/users.vue
```

## 页面与路由（`src/pages.json`）

| uni 页面路径 | 对应 web 路由 | 页面 | 说明 |
|---|---|---|---|
| `pages/index/index` | `/` | 首页 | Banner + 热门榜单 + 最新更新 + 分类精选 |
| `pages/search/index` | `/search` | 分类浏览 / 搜索 | 关键词 + 分类 + 排序 + 分页；站内搜不到时**搜源站并导入** |
| `pages/latest/index` | `/latest` | 最近更新 | 卡片网格（`sort=updated`），带相对时间角标 |
| `pages/rank/index` | `/rank` | 排行 | 分类区块懒加载（滚入视口才拉）+ 块内热度前 10 |
| `pages/comic/index` | `/comic/:id` | 详情页 | 封面/简介/标签/多源标注 + 收藏 + 章节列表 + 续读 |
| `pages/reader/index` | `/reader/:comicId/:chapterId` | 在线阅读器 | 双阅读模式、主题切换、章节切换、进度记忆 |
| `pages/me/index` | `/me` | 我的 | 最近阅读（续读/删除）+ 我的收藏 |
| `pages/login/index` | `/login` | 登录/注册 | JWT 登录；收藏需登录，历史匿名 |
| `pages/admin/index` | `/admin` | 采集管理台 | 采集/巡检/封面自愈；**需管理员** |
| `pages/admin/logs` | `/admin/logs` | 运行日志查询 | 按级别/源站/事件/作品/时间窗筛；**需管理员** |
| `pages/admin/users` | `/admin/users` | 授权管理 | 普通管理员 ⇄ 普通用户；**仅超管** |

> 管理台三页**不做 H5 专属**：移动端同样可访问（顶栏入口按角色显示，与桌面一致）。

顶栏导航由 `components/Layout.vue` 渲染（**每个页面用 `<Layout>` 包住自身内容** —— uni 没有全局路由出口，
所以 `comic-web/App.vue` 的 `<RouterView />` 换成了 `<slot />`）。

## 兼容层设计（`src/utils/`）

移植的关键是**让页面代码不必改写法**，因此做了三层薄封装：

| 模块 | 替代 | 说明 |
|---|---|---|
| `utils/router.ts` | vue-router | 导出同形的 `useRoute()` / `useRouter()`；`route` 只承载「当前 web 路径 + query」（供顶栏高亮、查询页读取）。`toUniUrl()` 把 `/comic/3`、`{path:'/search',query:{…}}` 解析成 `pages/comic/index?id=3`。`openNewTab()` 在 H5 开新标签，其他端退化为同页跳转。 |
| `utils/storage.ts` | localStorage | `get/set/remove` 三方法，语义与 `localStorage` 一致（读不到返回 `null`），底层是 `uni.getStorageSync/setStorageSync/removeStorageSync`。 |
| `utils/event.ts` | `window` 自定义事件 | `emit/on/off` → `uni.$emit/$on/$off`（H5/小程序/App 均可用）。 |
| `utils/guard.ts` | vue-router 的 `beforeEnter` | uni 页面栈**没有路由守卫钩子** → 抽成 `requireRole(superOnly, fullPath)`，由三个管理台页面在 `onLoad` 里 `await` 一次；返回 `false` 时终止本页加载。三步语义与 comic-web 一致（未登录→登录页 / `refresh()` 复核角色 / 角色不够→回首页+消息提示）。 |
| `api/request.ts` | axios | `uni.request` 单通道；`request<T>(path,{method,data,params})` 签名不变，`params` 由本层序列化进 query；错误文案仍取后端 `detail`/`message`（中文提示不被吞）。 |

### 与 vue-router 的差异（页面里必须知道的两点）

1. **路由参数走 uni 的 `onLoad(options)`** —— uni 页面栈没有 `route.params`。
   例：`pages/comic/index.vue` 用 `onLoad((o) => { comicId = Number(o.id); setRoute(...) })`；
   `pages/reader/index.vue` 用 `o.comicId` / `o.chapterId`。
   `route.path/query` 由页面在 `onLoad` 里调 `setRoute(path, options)` 登记。
2. **同页查询变更**（如搜索页切分类）—— uni 不允许 `navigateTo` 到自身，`router.replace` 在同页时
   只做「本地状态 + H5 地址栏 `history.replaceState` 同步」，不做页面跳转（行为与 vue-router 等价）。
3. **管理台门卫是「页面内调用」而不是路由钩子** —— uni 没有 `beforeEnter`，所以
   `pages/admin/{index,logs,users}` 在 `onLoad` 里 `await requireRole(...)`，未通过则本页不渲染（`v-if="ready"`）
   并跳登录页。**行为与 comic-web 一致**：未登录访问 `/#/admin*` 会落到登录页，而不是显示半截管理台。
4. **H5 的地址栏是 uni 自己的页面路径** —— `#/pages/rank/index`、`#/pages/comic/index?id=43`，
   **不是** comic-web 的 `#/rank`、`#/comic/43`。站内跳转由 `toUniUrl()` 统一转换，功能不受影响；
   但**收藏书签 / 外部分享链接**要按 uni 这套路径写。

### 移植时对 `comic-web` 的**五处有意**调整

前三条是**逻辑**调整，后两条是**视觉/控件**调整（用户明确指定）：

| # | 位置 | 原状 | 现状 | 原因 |
|---|---|---|---|---|
| 1 | `pages/reader` 的 `chapterId` | 取 `route.params` 的 `const`（**换章后不更新** → 上一章/下一章按钮状态与目录高亮会失真） | 改为 `ref`，`goChapter()` 同步更新 | 顺带修掉这个潜在缺陷；其余行为不变 |
| 2 | `pages/reader` 的 `route.params.chapterId` watcher | 监听参数变化重新加载 | 删除（`goChapter()` 本就显式 `loadChapter()`） | 避免同一次换章重复加载 |
| 3 | `pages/search` 的 `watch(() => route.query)` | 监听 query 对象 | 改看 `route.fullPath`（字符串按值比较） | 兼容层的 `route.query` 每次登记都是新对象，按引用比较会重复触发 |
| 4 | `pages/login` 的返回按钮 | 在**卡片外**左上方（锚在 `.auth-wrap` 上绝对定位）、灰色 `var(--text-2)` | 移到**卡片内**左上角（`.auth-card { position: relative }`，内缩 16/14px）、绿色 `#15803d` | 2026-09-22 用户指定的视觉调整。绿色为就地取值 —— 调色板（`style.css`）只有暖橙/琥珀，**未**新增变量以保持 `style.css` 与 comic-web 同源 |
| 5 | 管理台**日期控件**（`pages/admin/index` 3 处、`pages/admin/logs` 2 处） | 直接写 `<input type="date">`（浏览器原生日期选择器） | 改用 `components/DateInput.vue`（H5 端仍产出**原生** `<input type="date">`，其它端降级为文本输入） | uni 的 `<input>` 组件**不支持 `type="date"`**（见下文坑 5），原生选择器会被抹掉；组件用**渲染函数** `h('input')` 绕开模板编译，拿回原生控件。详见「日期控件」小节 |

## uni 内置组件样式归一化（`src/uni-compat.css`）

> **一句话**：`comic-web` 的样式表是按**原生** `input` / `button` / `form` 写的。搬到 uni-app 后它们被编译成
> **内置组件**（`uni-input` / `uni-button` / `uni-form`），而组件**自带一套默认样式 + 一层多余结构**，
> 于是「CSS 一字未改却错位」。这份文件只做一件事：**把 uni 组件归一化回原生元素的盒子模型**，
> 其余样式表原样生效 —— 不改业务、不改模板结构。

uni 的编译器会把 scoped CSS 里的 `input` / `button` 自动改写成 `uni-input` / `uni-button`，
所以**「样式没生效」不是选择器的问题**，是下面这些默认行为在作祟：

| # | uni 的默认行为 | 造成的错位 | 归一化 |
|---|---|---|---|
| ① | `uni-form` 在子元素外**再包一层 `<span>`**（组件内部写死） | `.big-search { display:flex }` 落在 `uni-form` 上、真正的 input/button 在那层 span 里 → **flex 从未生效**，搜索框与按钮各占一行、按占位符宽度收缩 | `uni-form > span { display: contents }` |
| ② | `uni-button` 默认 `display: block` | 未设宽度的按钮**占满整行**（登录页「没有账号？去注册」本该只有 124px，实测变成 360px） | `html uni-button { display: inline-flex }` |
| ③ | `uni-button` 靠 `line-height: 2.5555` **近似**垂直居中 | 业务 CSS 一旦改掉 line-height（如搜索按钮 `.big-search button` 没写 line-height），**文字就贴顶** —— 实测上边距 0px / 下边距 24px | `align-items: center; justify-content: center`（**原生 `<button>` 的内容盒本来就是浏览器匿名盒居中的**，uni 只是用行高近似） |
| ④ | `uni-button` 默认 `margin-left/right: auto` | 按钮在**任何 flex 行**里都被吸到两端 → 分类标签 / 排序 / 分页被整行撑散 | `margin: 0` |
| ⑤ | `uni-button` 默认 `padding-left/right: 14px`、`font-size: 18px` | 未声明内边距/字号的按钮比原生宽 16px、字大一圈（原生 UA 默认是 `padding: 1px 6px`、`font-size: 13.3333px`） | `padding: 1px 6px; font-size: 13.3333px` |
| ⑥ | `uni-button` 默认 `overflow: hidden` | 消息中心铃铛上的**未读红点被裁掉** | `overflow: visible` |
| ⑦ | `uni-button` 默认用 `::after` 画 1px 边框 | 无边框的纯文字按钮多出一个方框（登录页「← 返回」「没有账号？去注册」） | `html uni-button::after { border: none }` |
| ⑧ | `uni-input` 写死 `height/min-height: 1.4em` + `box-sizing: border-box`，内部 `.uni-input-wrapper` / `.uni-input-input` 又是 `height: 100%` | 业务 CSS 只给 padding 不给 height 时（登录页 `.field input { padding: 11px 14px }`），内容盒高度 = `1.4em − padding` **算成 0** → **真正的 `<input>` 高 0px，点不进去、打不了字**（实测输入框 41px → 24px、内层 0px） | `height: auto; min-height: 0` + `.uni-input-input { height: auto }`（原生 input 的高度本来就是「行高 + 内边距 + 边框」由内容撑开） |
| ⑨ | `uni-input` 默认 `line-height: 1.4em` | 比原生（`normal`）高 4px | `line-height: normal` |
| ⑩ | uni 组件**继承 body 字体栈** | 原生 `<button>` / `<input>` **不继承页面字体**（UA 用 `Arial`，实测计算值 `font-family: Arial`）→ Arial 与「PingFang / 微软雅黑」行盒高度不同（15px 下 17px vs 20px），输入框整体高 3px、按钮文字行盒也差 3px | `html uni-button, html uni-input { font-family: Arial }` |
| ⑪ | uni 的 `<label>` 组件**只要有子内容**就挂上 `.uni-label-pointer`（源码里「`props.for` 有值**或**有默认插槽」即为真），而原生 `<label>` 的 UA 默认是 `cursor: default` | 登录页「用户名 / 密码」两行**说明文字**凭空出现小手 —— 它们只是 label 里的文字、并不可点。而且 `cursor` 是**继承属性**，这一个 pointer 会一路传给 `.field span`、`uni-input`、`.uni-input-wrapper`、`.uni-input-placeholder` | `html uni-label.uni-label-pointer { cursor: default }`。真正可点的元素**各自显式声明** pointer（`.btn` / `.switch` / `.back` 都写过），scoped 编译后带属性选择器 = 0,2,0，权重高于本行，不受影响；admin 的 `<label class="switch">` 由内部 `.slider` 兜住，行为与 comic-web 一致 |

### 五个必须知道的坑

1. **选择器必须带 `html` 前缀。** uni 的组件样式是**运行时用 `insertRule` 写进 CSSOM** 的 —— 它
   **不出现在静态 HTML 里**（`--dump-dom` 看不到），而且**注入在本文件之后**。同权重（`uni-button` 都是
   0,0,1）时后者胜出，重置会**静默失效**。加 `html` 变成 0,0,2（`::after` 是 0,0,3）就不受注入顺序影响。
2. **`html` 前缀只够压「元素选择器」，压不住「类选择器」。** 第 1 条只能把 `uni-button` 抬到 0,0,2；
   若 uni 自己的规则用的是**类**（如 `.uni-label-pointer` = 0,1,0），`html uni-label`（0,0,2）**照样输** ——
   必须把类名一起写上：`html uni-label.uni-label-pointer` = 0,1,2。**改任何一条前先算权重，别只看前缀。**
3. **表单提交要用 uni 语义。** `uni-form` 不是原生 `<form>`：按钮必须写 **`form-type="submit"`**
   （写 `type="submit"` 是**死按钮**，不触发提交）；`@submit` **不要加 `.prevent`**（uni 合成事件没有 default）；
   输入框按回车提交要监听 **`@confirm`**（没有原生表单的隐式回车提交）。
   → 涉及页面：`components/Layout.vue`、`pages/search/index.vue`、`pages/admin/users.vue`、`pages/login/index.vue`。
4. **业务 CSS 权重更高，不会被本文件覆盖。** 本文件是 0,0,2（`::after` 是 0,0,3），而 comic-web 的
   `.field input` 编译成 `.field uni-input` 是 0,1,1 —— 所以业务**显式写过**的属性（width / height / padding /
   font-size / border …）照旧生效，本文件只兜底那些**没写**的属性（= 原生 UA 默认值）。
5. **`uni-input` 的 `type` 是白名单，`date` 会被抹成 `text`。** 源码里
   `INPUT_TYPES = ['text','number','idcard','digit','password','tel']`，白名单外的值一律
   `type2 = 'text'` —— 于是 `<input type="date">` 编译成 `uni-input` 后，**原生日期选择器直接消失**，
   只剩一个普通文本框（2026-09-22 管理台日期控件「全都不行」就是这个原因）。
   → 走 `components/DateInput.vue`：H5 端用**渲染函数** `h('input', { type: 'date' })` 产出原生控件
   （`h()` 是**运行时**调用、不经模板编译，Vue 对字符串 tag 直接建原生元素，绕开 easycom 把
   `_resolveComponent("input")` 换成 uni 组件的那一步）。

### 日期控件（`components/DateInput.vue`）

- **H5**：原生 `<input type="date">`（与 comic-web 的观感一致，`showPicker()` 可用）；**其它端**：文本输入 `YYYY-MM-DD`。
- **样式由页面负责**：uni 会把 scoped CSS 的 `input` 改写成 `uni-input`，**匹配不到**这个原生 input。
  组件根元素固定带 `class="date-inp"` 作为钩子，页面的输入框样式规则要**额外挂上 `.date-inp`**
  （`admin/index` 的 `.row-inputs`、`admin/logs` 的 `.filters` 都已挂）。
  作用域没问题：Vue 会把**父页面的 `data-v-*`** 也加到子组件根元素上（`setScopeId`），页面 scoped 样式能命中。

> 小程序 / App 端 uni 不注入这层 `<span>`、也不注入 H5 的那套组件 CSS，所以本文件里的规则在那些端**自然空转**，
> 同一份模板照样正确 —— 属于 H5 专属适配，但不是 H5 专属代码。

### 对齐验证方法（可复现）

本机 `agent-browser` CLI 不在 PATH，用 **CDP 直连无头 Edge** 做「comic-web vs comic-front 同页对照」：
读 `getBoundingClientRect()` + `getComputedStyle()` + `Range.getClientRects()`（后者拿按钮**文字**的真实渲染框，
用来判断有没有居中）。在 **1280 / 900 / 760 / 600 / 480 / 390** 六个视口宽度下逐项比对，
登录页的 `.auth-card` / `.field input` / `.switch`，与搜索页的搜索按钮，**全部逐像素一致**。

> ⚠️ **例外**：登录页的 `.back` 自 2026-09-22 起**有意**与 comic-web 不同（移入卡片内左上角 + 绿色字体，
> 见上文「有意调整」第 4 条），**不在**对齐比对范围内 —— 其余项目仍要求逐像素一致。

## 本地运行

前置：后端 8000 已在运行（`api-service`，MySQL 数据）。接口统一相对路径 `/api/*`，由 Vite proxy 转发到 `127.0.0.1:8000`。

```bash
npm install
npm run dev:h5          # H5 开发 http://localhost:5174（HMR，/api 代理到 8000）
npm run build:h5        # H5 生产构建 → dist/build/h5
npm run dev:mp-weixin   # 微信小程序开发（产物在 dist/dev/mp-weixin，用微信开发者工具打开）
npm run build:mp-weixin # 微信小程序构建
npm run dev:app         # App（需 HBuilderX 配合打包）
```

> ⚠️ **端口用 5174，与 comic-web 的 5173 错开**：两者若都监听 5173，一个绑 `127.0.0.1`、一个绑 `0.0.0.0`，
> 浏览器访问 `127.0.0.1:5173` 会被 comic-web 抢走（静默打开错的应用）。错开后两个前端可同时运行。

### 已验证（2026-09-21）

- `npm run build:h5` 通过（11 个页面全部编译，0 警告）；`tsc --noEmit` 0 错误。
- 用无头浏览器逐个渲染全部 11 个路由：均渲染出真实数据、无 Vite 错误浮层。
  桌面 1440px 与手机 390px 两种视口下布局均正常（顶栏在窄屏收成「logo + 🔔 + 登录 + ☰」）。
- `/api/*` 经 dev server 代理到 `:8000` 正常（首页/详情/排行等都拿到真实数据）。
- 管理台门卫生效：未登录访问 `#/pages/admin/{index,logs,users}` 均落到登录页。
- **与 comic-web 逐像素对齐已复核**（2026-09-21，CDP 直连无头 Edge，6 个视口宽度 1280/900/760/600/480/390）：
  登录页 `.auth-card` / `.field input` / `.switch`，与搜索页 `.big-search` 内的
  输入框与搜索按钮，**矩形全部一致**（如 1280px 下：输入框 41px 高、`.switch` 124×21、
  搜索按钮文字上/下边距 14/13 居中）。
  *（登录页 `.back` 原也在比对范围内，自 2026-09-22 起按用户要求**有意**改为「卡片内左上角 + 绿色」，已移出。）*
- **登录页返回按钮改版已复核**（2026-09-22，同一套 CDP 无头验证）：6 个视口下
  `inCard=true`、`parentElement=.auth-card`、内缩固定 **left 16px / top 14px**、
  计算色 **`rgb(21, 128, 61)`**（绿色）、hit-test 命中 `uni-button.back`、
  与 `.brand-mark` **无矩形重叠**、无横向溢出、无 JS 报错。
- **功能性验证通过**：输入框内层 `<input>` 高 17px、点击命中真身、`activeElement` 正确、可输入；
  **回车（`@confirm`）与点击「登录」（`form-type="submit"`）都能触发表单提交**。
  全 11 个路由扫描：无 0 高输入框 / 按钮、无横向溢出、**无 JS 报错**。
- **光标（`cursor`）审计已复核**（2026-09-22，CDP 直连无头 Edge，1280px）：把 login / search / home 三页
  所有 `cursor: pointer` 的元素**逐个列出、按 uni→原生标签名归一后做差集**，两端**完全一致**（0 差异）。
  登录页明细：`.field=default`、`.field span=default`（「用户名 / 密码」不再是小手）、`.field input=text`、
  `.btn.block` / `.switch` / `.back=pointer`（与 comic-web 相同）。
  另用**注入仿 scoped 规则**（`.fake-slider[data-v-test]` = 0,2,0）复刻 admin 的 `<label class="switch">`，
  确认 `.slider` 仍是 `pointer`、而 `label` / `.heal-field` 是 `default` —— 即新规则**没有误伤**可点的开关。
- **管理台日期控件已复核**（2026-09-22，CDP 直连无头 Edge，在真实 dev 环境动态 import 组件后挂载）：
  渲染结果是**原生** `<input data-v-* class="date-inp" type="date">`（**不是** `<uni-input>`）、
  `el.type === 'date'`、`showPicker` 为函数（真原生选择器）、`v-model` 值正确回填
  （`2026-09-14`）、页面规则命中（`min-width: 90px` / `border: 1px` / `radius: 7px` / `font-size: 13px`）。
  另核对两页**编译后**的 scoped CSS：`admin/index` 得 `.row-inputs .date-inp[data-v-f94c733c]`、
  `admin/logs` 得 `.filters .date-inp[data-v-a9a83420]`（含 `min-width: 138px`），钩子均已挂上。

## 依赖说明

| 依赖 | 用途 | 备注 |
|---|---|---|
| `@dcloudio/uni-app` 等 | uni-app 运行时与编译 | **必须用 `vue3` 系列版本**（`3.0.0-*`）；`latest` 是 Vue2 线，会拉错 |
| vue 3 | 框架 | 与 comic-web 同版本线 |
| **pinia** | 登录态 / 消息中心全局共享 | 与 comic-web 一致用 pinia@2 |
| `@dcloudio/vite-plugin-uni` | 构建插件 | 其 peer 要求 **vite 5.2.8**（精确版本），已锁 |

## 多端待办（小程序 / App）

当前为 **H5 双端优先**版本，模板仍使用 HTML 标签（`div` / `p` / `img` / `button` / `table` / `select`），
uni-app 在 H5 下直接按标准 HTML 渲染，因此视觉与 `comic-web` 完全一致。要真正跑通小程序 / App，需要：

1. **标签映射**：`div/section/header/footer/main/nav/p/h1-h4` → `view`；`span/em/small` → `text`；
   `img` → `image`（配 `mode="aspectFill"`）；`button` → `view`+`@click`（uni 的 `button` 有默认样式，
   见上文「uni 内置组件样式归一化」）；`select` → `picker`；`table` → `view` 弹性布局；
   同时把 CSS 里的元素选择器（`.nav-links a`、`.cover img` 等）改成类选择器。
2. **阅读器交互**：`pages/reader` 目前依赖 H5 的 `PointerEvent` / `requestAnimationFrame` /
   `element.scrollTo` / `getBoundingClientRect`，需改用 `touchstart/touchmove/touchend` + `uni.pageScrollTo` / `scroll-view`。
3. **排行页懒加载**：`IntersectionObserver` 需换成 `uni.createIntersectionObserver`（或 `onReachBottom` 兜底）。
4. **H5 专属 API 复核**：`document.addEventListener`（Layout 点击空白关面板）、`window.innerWidth`、
   `window.addEventListener('keydown')`（阅读器键盘翻页）—— 已在代码里用 `// #ifdef H5` 条件编译保护，
   非 H5 端不会报错，只是没有对应能力。
5. **`alert` / `window.alert`**：管理台与日志页的失败提示仍用浏览器弹窗（H5 可用）；要上小程序 / App
   需统一换成 `uni.showModal`（小程序无 `alert`）。
6. **`manifest.json`**：填小程序 `appid`，并按需配置 App 端图标/权限。

## 开发约定

- 日常只用 `npm run dev:h5`（5174），不构建产物；发布才 `build:h5`，由后端同源托管产物。
- **新增接口**：与 comic-web 完全同构 —— 内容类加到 `api/content.ts`、认证/收藏/历史加到 `api/user.ts`；
  需要新领域类型时在 `types.ts` 定义并 `import type`。
- **不要绕过兼容层**：页面里禁止直接 `import` vue-router / 直接用 `localStorage` / `window.dispatchEvent`，
  一律走 `utils/router`、`utils/storage`、`utils/event`，否则多端会立刻失效。
