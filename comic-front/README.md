# comic-front 前端（uni-app · Vue 3 + TypeScript + Vite + Pinia）

漫画聚合阅读平台的**移动端专用前端**，由 `../comic-web`（纯 Web SPA）一比一移植而来：

- **业务约定与逻辑完全不变** —— 页面结构、接口调用、登录态、消息中心、阅读器行为都与 `comic-web` 一致；
- **只换底层设施** —— vue-router → uni 页面栈、axios → `uni.request`、`localStorage` → uni 存储、
  `window` 自定义事件 → `uni.$emit`；差异全部收敛在 `src/utils/` 与 `src/api/request.ts`，业务层不感知；
- ⚠️ **只保留移动形态**（2026-09-23）：本端定位为**移动端专用**，网页端由 `comic-web` 承担，
  两者**端口与 Docker 镜像分开**、按需启动。因此所有**桌面专属元素与桌面断点已删除**，
  原来的移动端媒体查询规则**提升为基础态**（详见下文「桌面端适配已删除」）；
- `comic-web` 保留为参考实现、**代码不再改动**（仅作为网页端产物参与部署）。

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
    │   ├── Layout.vue        # 由 comic-web 的 App.vue 移植：顶栏 + 底栏导航 + 抽屉菜单 + toast（本端只有移动形态）
    │   ├── ComicCard.vue · Picker.vue · DateInput.vue
    ├── utils/                # 兼容层（comic-front 特有，见下）
    │   ├── router.ts · storage.ts · event.ts · guard.ts · ui.ts
    │   ├── theme.ts          # 主题（明亮 / 夜间）：状态 + 持久化 + 往根节点挂主题类
    │   ├── icons.ts          # 移动端底栏图标（自绘 SVG → base64 data URI，明亮/夜间各一套）
    └── pages/                # 每个页面一个目录（uni 约定），共 12 页
```

## 页面与路由（`src/pages.json`）

| uni 页面路径 | 对应 web 路由 | 页面 | 说明 |
|---|---|---|---|
| `pages/index/index` | `/` | 首页 | Banner + 热门榜单 + 最新更新 + 分类精选 |
| `pages/search/index` | `/search` | 分类浏览 / 搜索 | 关键词 + `FilterBar`（标签下拉 + 排序）+ 分页（每页 18 条）；站内搜不到时**搜源站并导入** |
| `pages/latest/index` | `/latest` | 最近更新 | 卡片网格（`sort=updated`，每页 18 条），带相对时间角标 |
| `pages/rank/index` | `/rank` | 排行 | **一整条全库榜单**（默认热度降序）+ `FilterBar`；触底追加下一页 |
| `pages/comic/index` | `/comic/:id` | 详情页 | 封面 / 简介 / 标签 / 来源标注 + 收藏 + 章节列表 + 续读 |
| `pages/reader/index` | `/reader/:comicId/:chapterId` | 在线阅读器 | 双阅读模式、主题切换、章节切换、进度记忆 |
| `pages/me/index` | `/me` | 我的 | 最近阅读（续读 / 删除）+ 我的收藏 |
| `pages/messages/index` | `/messages` | 消息中心 | 采集 / 巡检 / 自愈结果 + 系统消息；**顶栏铃铛的落点**（本端只有独立页，下拉浮层已随桌面端删除） |
| `pages/login/index` | `/login` | 登录 / 注册 | JWT 登录；收藏需登录，历史**登录后归属账号、游客用浏览器匿名 id** |
| `pages/admin/index` | `/admin` | 采集管理台 | 采集 / 巡检 / 封面自愈；**需管理员**。窄屏卡片单列铺开 |
| `pages/admin/logs` | `/admin/logs` | 运行日志查询 | 按级别 / 源站 / 事件 / 作品 / 时间窗筛；**需管理员**。窄屏表格→卡片 + 点行展开详情 |
| `pages/admin/users` | `/admin/users` | 授权管理 | 普通管理员 ⇄ 普通用户；**仅超管**。窄屏表格→卡片 |

> 管理台三页**不做 H5 专属**，移动端同样可访问（顶栏入口按角色显示）。

顶栏由 `components/Layout.vue` 渲染：**每个页面都要用 `<Layout>` 包住自身内容** —— uni 没有全局路由出口，
所以 `comic-web/App.vue` 的 `<RouterView />` 换成了 `<slot />`。

## 模块架构

### 兼容层（`src/utils/`）—— 让页面代码不必改写法

| 模块 | 替代 | 说明 |
|---|---|---|
| `router.ts` | vue-router | 同形的 `useRoute()` / `useRouter()`；`toUniUrl()` 把 `/comic/3`、`{path,query}` 解析成 `pages/comic/index?id=3`；`openNewTab()` 在 H5 开新标签、其他端退化为同页跳转 |
| `storage.ts` | localStorage | `get/set/remove`，语义一致（读不到返回 `null`），底层 `uni.*StorageSync` |
| `theme.ts` | 主题管理器 | `useTheme()` → `{ theme, isDark, setTheme, toggleTheme }`；选择存本地、未选过时跟随系统，并把主题类挂到根节点（见下文「主题」） |
| `event.ts` | `window` 自定义事件 | `emit/on/off` → `uni.$emit/$on/$off` |
| `guard.ts` | vue-router 的 `beforeEnter` | uni 页面栈没有路由钩子 → `requireRole(superOnly, fullPath)`，由三个管理台页面在 `onLoad` 里 `await` |
| `ui.ts` | `window.alert/confirm` | `showAlert` / `showConfirm`（内部 `uni.showModal`），小程序无 `window` |
| `api/request.ts` | axios | `uni.request` 单通道；`request<T>(path,{method,data,params})` 签名不变；错误文案仍取后端 `detail`/`message` |

**与 vue-router 的差异（页面里必须知道）**

1. **路由参数走 `onLoad(options)`** —— uni 没有 `route.params`；`route.path/query` 由页面在 `onLoad` 里调 `setRoute()` 登记。
2. **同页查询变更**（如搜索页切分类）：uni 不允许 `navigateTo` 自身 → `router.replace` 只做「本地状态 + H5 地址栏同步」。
   ⚠️ 这种写法**只给 `query`、不给 `path`**（`router.replace({ query: {...} })`），`toUniUrl()` 会补当前路径
   （`to.path || route.path`）。**别把这个兜底删掉**：缺了它 path 是 `undefined`，`toUniUrl` 里的
   `path.indexOf('?')` 直接抛 `TypeError: Cannot read properties of undefined (reading 'indexOf')`，
   而异常会打断调用方 —— `onCategory` 里跟在后面的 `load()` 就再也执行不到，表现为
   **点分类标签只切高亮、不查数据**（2026-09-22 用户报的就是这个）。
3. **管理台门卫是「页面内调用」**：在 `onLoad` 里 `await requireRole(...)`，未通过则整页不渲染并跳登录页。
4. **H5 地址栏是 uni 自己的路径**：`#/pages/rank/index`、`#/pages/comic/index?id=43`（**不是** `#/rank`）——
   站内跳转由 `toUniUrl()` 转换，但**书签 / 外链要按 uni 这套路径写**。

**对 `comic-web` 的十五处有意调整**（第 1~3 条是逻辑，其余是视觉 / 控件 / 交互）

| # | 位置 | 现状 | 原因 |
|---|---|---|---|
| 1 | `pages/reader` 的 `chapterId` | 由 `const` 改 `ref`，`goChapter()` 同步更新 | 原写法换章后不更新，上下章按钮与目录高亮会失真 |
| 2 | `pages/reader` 的参数 watcher | 删除 | `goChapter()` 本就显式 `loadChapter()`，避免重复加载 |
| 3 | `pages/search` 监听 `route.fullPath`（字符串） | 不再监听 `route.query` 对象 | 兼容层的 `query` 每次登记都是新对象，按引用比较会重复触发 |
| 4 | `pages/login` 返回按钮 | 移入卡片内左上角（内缩 16/14px）、绿色 `#15803d` | 用户指定的视觉调整；绿色就地取值，**未**新增调色板变量以保持 `style.css` 与 comic-web 同源 |
| 5 | 管理台日期控件（5 处） | 改用 `components/DateInput.vue`（H5 仍是原生 `<input type="date">`，其它端降级为文本输入） | uni 的 `<input>` **不支持 `type="date"`**（白名单外会被抹成 `text`） |
| 6 | 导航（全端统一） | 顶栏精简为「菜单 · 搜索 · 消息 · 主题」，主导航移到**底部固定栏**；账号入口收进左侧滑出菜单 | 用户指定的交互调整；comic-web 无此形态，详见下文「底栏导航」。⚠️ 2026-09-23 起**不再有宽窄屏之分**，这套形态就是本端唯一形态 |
| 7 | 移动端封面网格列数 | 手机（≤560px）由 2 列改 **3 列**、间距收到 10px；`ComicCard` 配套收紧字号 | 用户要求「移动端每行三部、增加信息量」；详见下文「移动端漫画列表」 |
| 8 | `style.css` 的 `.page` | `padding: 20px 0 48px` → `20px 16px 48px` | 原写法把 `.container` 的 `0 16px` 覆盖成 0 → 窄屏内容贴屏幕边缘 |
| 9 | 首页各区块（热门 / 最新 / 分类精选） | 每块由 5–8 部统一改 **3 部**、网格由 `.grid-5` 改 `.grid`，标题行右侧加「全部 ›」 | 用户要求「只显示排名最前的三部，其余走链接」 |
| 10 | 主题（明亮 / 夜间） | 新增，顶栏右侧一个 🌙/☀️ 按钮切换 | 用户要求；comic-web 只有明亮一套 |
| 11 | 漫画明细页移动端 | 封面挪到卡片左上、明细+按钮在右上；章节列表改 **每行 4 个**网格 | 用户要求「适配移动端」；详见下文「漫画明细页」 |
| 12 | 阅读器页面图宽度 | 横向 `92vw` → `100vw`、竖排 `96vw` → `100vw`（并隐掉 scroll-view 的 8px 滚动条） | 用户要求「左右黑边都去掉」；详见上文「阅读器页面图尺寸」 |
| 13 | 分类页 / 排行页的筛选 | 分类页的 30 个标签 chip 平铺 → **下拉单选**；排行页的「每标签一块」→ **一整条全库榜单**；两页共用 `components/FilterBar.vue`（标签 + 排序），默认**热度降序** | 用户要求「新增标签条件和热度、收藏筛选，默认按热度降序；去掉全部标签展开，排行榜不必每个标签单独排序」；详见下文「筛选条」 |
| 14 | 页脚 | **整块删除**（品牌行 + 「● 已连接采集服务」状态标签 + 「仅收录…」版权提示）；给底栏清障的 `padding-bottom: 84px` 从 `.footer` **搬到 `.page`** | 用户要求；窄屏下和固定底栏一起挤，一屏剩不下多少内容。⚠️ 清障高度不能跟着页脚一起消失，否则最后一排卡片被底栏压住 |
| 15 | 管理台三页（≤860px） | 日志页 / 授权页的 flex 表格 → **纵向卡片**（日志页带伸缩展开：点行看全部字段）；采集页 `.grid`/`.maint-row` 的 `minmax(360px,1fr)` → `1fr` | 用户要求「采集和日志页面也要适配移动端，表格列太多可以换成伸缩展开的模式，点击之后可以查看每个日志的详情，**不允许出现横向滑动条**」；详见下文「窄屏不许横向滚动条」 |
| 16 | 桌面端适配 | **整体删除** —— 桌面专属元素（logo / 顶栏主导航 / 用户胶囊 / 退出 / 登录链接 / 消息下拉浮层 / 页脚）与桌面断点（860 / 900 / 760 / 700px）全部移除，移动态提升为基础态 | 用户要求「comic-front 适配桌面端删掉，移动端启动这个端口、网页端启动 comic-web 端口，端口区分开、改成两个 docker 镜像」；详见下文「桌面端适配已删除」 |

### 桌面端适配已删除（2026-09-23）

**背景**：comic-front 原先是一套**响应式**前端（基础样式是桌面态，靠 `@media (max-width: 860px)`
反向覆盖成移动态）。用户决定把两端**彻底分开**：网页端交给 `comic-web`、移动端用本端，
两者端口与 Docker 镜像独立、按需启动。于是本端**只保留移动形态**。

**改造手法：不是「删样式」，而是「把移动态提为基础态」**

| 原来 | 现在 |
|---|---|
| 基础样式 = 桌面态，`@media (max-width: 860px)` 覆盖成移动态 | **移动态写在基础态**，断点整块删除 |
| 桌面专属元素在窄屏 `display: none` | 元素**从模板里删掉**（DOM 都不生成，比隐藏干净） |
| ≤560px 断点 = 手机内部微调 | **保留**（它不是桌面规则，是手机内的间距/字号收紧） |

**逐处改动**

| 位置 | 改动 |
|---|---|
| `components/Layout.vue` | 模板删掉 `.logo` / `.nav-links`（7 项主导航）/ `.user-chip` / `.logout` / `.login-link` / `.footer` / `.msg-panel` 浮层 / `.msg-mask`；底栏 `.bottom-nav` 与 `.menu-btn` 改为**恒显示**；`.menu-mask` / `.mobile-menu` 样式移到文件末尾无条件生效；脚本删掉 `backendAlive` 探活、`showMsg` 系列、`onUserClick`、`document` 监听 |
| `pages/index/index.vue` | `.grid` 基础态 4 列 → **3 列**；删 900px 断点 |
| `pages/latest/index.vue` | `.grid` 基础态 6 列 → **3 列**；删 900px 断点（`pageSize` 仍 18 = 3×6） |
| `pages/search/index.vue` | `.grid` 基础态 6 列 → **3 列**；删 900px 断点（同上） |
| `pages/me/index.vue` | `.fav-grid` 基础态 6 列 → **3 列**；`.row-actions` 竖排提升为基础态；删 900px 断点 |
| `pages/rank/index.vue` | `.rank` 基础态 2 列 → **1 列**；删 760px 断点 |
| `pages/comic/index.vue` | hero 提升为移动态（封面 96×128 左上 + 明细右上，横向卡片）；章节 4 列并隐藏序号徽标；删 700px 断点 |

**改这里时别踩的坑**

- ⚠️ **`order` 重排依赖 DOM 顺序不变**：顶栏靠 flex `order`（菜单 1 / 搜索 2 / 消息 3 / 主题 4）
  把 ☰ 顶到最左，而 DOM 里的顺序仍是「搜索 · 消息 · 主题 · 菜单」。删元素时别顺手调整 DOM 顺序。
- ⚠️ **底栏清障必须留在 `.page` 上**：`.page { padding-bottom: 84px }`（+ `env(safe-area-inset-bottom)`）
  是防止最后一排卡片被固定底栏压住。页脚已删，这条是**唯一**的清障来源，删了就会压住内容。
- ⚠️ **`.page` 的左右 16px 不能省**（见下文「移动端漫画列表」最后一条）。
- ⚠️ **`.chapter .no`（序号徽标）是 `display: none`，不是从模板删的**：章节标题本身就是「第 12 话」，
  4 列下每格只剩 ~80px，徽标会占掉一半宽度。留着 `display: none` 是为了保留模板结构、
  便于日后想恢复时只改一行 CSS。

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
| `div/section/header/nav/ul/li/p/h1-h4/table 系` → `view` | 块级；**表格换完标签还要用 flex 重搭，见下方 ⚠️** |
| `span/b/em/small/code` → `text`；**`label` → `view`** | `label` 是 flex 容器，且 `<text>` 内不能放表单组件 |
| `a` → **`view`** | 卡片外层 `a` 包着 `view`/`image`，**不能**映射成 `text`（小程序禁止 `<text>` 内放块级组件） |
| `img` → `image` | **必须自己给宽高**（`<uni-image>` 无固有尺寸，见下）＋按需选 `mode`：`aspectFill`=裁剪填满 / `aspectFit`=等比不裁剪 / `widthFix`=宽度定、高度按比例自动 |
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
| `@click.self` → **`@click.stop`（遮罩上关闭 + 面板自身 `@click.stop` 拦冒泡）** | 阅读器两个弹层（目录 / 设置） |
| `<transition>` → CSS `@keyframes` | 消息面板 / toast / 弹层 / 移动端菜单抽屉（小程序不支持 transition 组件） |
| `window.alert/confirm` → `utils/ui.ts` | 日志页清理确认 |
| `document` 点击关面板 → 保留 H5 分支 + `#ifndef H5` 透明遮罩 | 顶栏消息中心 |
| `aspect-ratio` → padding-bottom 比例盒 / 写死高度 | 卡片、书架、缩略图 |
| `inset: 0` → 显式四边偏移 | 阅读器根元素（`inset` 需 Chrome 87+） |
| `button` 默认样式 → `App.vue` 的 `<style>`（`#ifdef MP-WEIXIN`） | 全站按钮 |

### ⚠️ `<image>` 的盒子模型（踩过坑，必读）

uni 的 `<image>` **不是 `<img>`**，而是包装元素 `<uni-image>`；真正画图的是它内部那个 `<div>` 的
`background-image`。而 `uni-components/style/image.css` 给 `<uni-image>` 的**默认尺寸是 `320px × 240px`**
—— 也就是说：**`<uni-image>` 没有固有尺寸，宽高必须由 CSS 显式给**（原生 `<img>` 能靠图片自身撑开，它不能）。

把 comic-web 写给原生 `<img>` 的 CSS 原样搬过来会出两类错（阅读器 2026-09-22 就中了）：

| 写法 | 结果 |
|---|---|
| `width: auto; height: auto` | `<uni-image>` 是 inline-block、子节点全是绝对定位 / 百分比 → 收缩成 **0×0，整屏无图** |
| 只写 `max-width` / `max-height` | `max-*` 只「限制」不「撑开」→ 回落到默认 **320×240，图很小** |

`mode` 的语义（uni 源码 `IMAGE_MODES` / `FIX_MODES`）：

| mode | 实现 | 适用 |
|---|---|---|
| `aspectFill` | `background-size: cover`（按框裁剪填满） | 封面 / 缩略图这类**有固定方框**的图 |
| `aspectFit` | `background-size: contain`（等比不裁剪） | 单张居中阅读（等价原生 `img` + `max-width/max-height`） |
| `widthFix` | 按 `offsetWidth ÷ 原图宽高比` 算高度 | 竖排连播（宽度定、高度自适应） |

> `lazy-load` 在 uni-h5 基本不生效（Image 在 `onMounted` 就直接加载），别指望它省流量。

### 阅读器页面图尺寸（满幅，左右不留黑边）

给 `<uni-image>` 的方框就是「视口里能放下的最大框」，宽度取 `min(视口宽, 可用高度 × 0.705)`：

| 模式 | 宽度 | 高度 |
|---|---|---|
| 横向（单张居中） | `min(100vw, calc((100vh - 40px) * 0.705))` | `calc(100vh - 40px)` |
| 竖排（连播） | `min(100vw, 720px)` | `auto`（配 `widthFix`） |

- 两项取 `min` 是为了**两种受限方向都覆盖**：手机竖屏走「宽度受限」（= `100vw`，图片铺满、左右无黑边），
  桌面走「高度受限」（`(100vh - 40px) × 0.705`，不会撑成一条巨大横幅）。
- 原来是 `92vw` / `96vw`，手机竖屏下左右各留 4vw / 2vw 的**黑边**（2026-09-23 改满幅）。
- ⚠️ **竖排模式还额外中了一刀**：uni 的 `<scroll-view>` 内层 `uni-scroll-view` 在桌面 Chrome 下
  **实占 8px 滚动条宽**（实测 `offsetWidth - clientWidth = 8`），把 `100vw` 的图挤成 382px、右侧露黑边。
  靠 `:deep(.uni-scroll-view)::-webkit-scrollbar { display:none }` + `scrollbar-width: none` 隐掉 ——
  阅读区本来就是全幅暗色层，位置由底部进度条反映，不需要滚动条。

### ⚠️ 弹层遮罩关闭（踩过坑，必读）

`@click.self` 是 **Web 专有修饰符**（小程序不支持），移植时容易改成「比较 `target` 与 `currentTarget`」——
**这个替代方案在 uni 里是坏的**：uni 会重写事件对象，`currentTarget` 不可靠地指向遮罩节点，
判定恒真 → 遮罩点了永远关不上（阅读器目录 / 设置两个抽屉 2026-09-22 就中了）。

**正确写法**：遮罩上直接关，面板自己 `@click.stop` 拦住冒泡。

```vue
<view v-if="showMenu" class="menu-mask" @click.stop="showMenu = false">
  <view class="chapter-menu" @click.stop> ... </view>
</view>
```

`.stop` 小程序 / H5 都支持；遮罩上的 `.stop` 还顺带挡住点击冒泡到根节点（否则会触发根节点的翻页热区）。

### ⚠️ 弹层的进场 / 退场动画（踩过坑，必读）

`v-if` 是「挂载即出现、卸载即消失」，只有进没有出 —— 观感就是**原地弹出 / 弹没**。
要做「从左侧滑出」这类动效，统一用 **CSS 动画 + 定时器**（不用 `<transition>`，小程序不支持）：

| 环节 | 做法 |
|---|---|
| 进场 | 元素自带 `animation: drawer-in 0.24s ...`（`translateX(-100%) → 0`），挂载即自动播放 |
| 退场 | 关闭时**先挂 `.closing` 类**换成 `drawer-out`，等 `MENU_ANIM_MS` 到点再置 `v-if=false` 卸载；直接卸载会「秒没」 |
| 幂等 | 关闭入口有多个（× 按钮 / 点遮罩 / 路由变化 / 菜单项），`closeMenu()` 用「已关闭或已在收起中则 return」保证不重复计时 |
| 卸载前 | `onBeforeUnmount` 里 `clearTimeout`，别让定时器活过组件 |

⚠️ **页间跳转必须等动画播完再 `router.push`**：uni 的跳转是**页面级**的（每个页面各自持有自己的
`Layout`），push 的瞬间当前页连同 Layout 一起被卸载，抽屉会跟着秒消失、动画白做 ——
`Layout.vue` 的 `goFromMenu()` 因此把 push 延后到动画结束（2026-09-22）。


### ⚠️ 表格：`table` 换成 `view` 后必须用 flex 重新搭（踩过坑，必读）

uni 没有 `<table>`（小程序也不支持）。移植时把 `table/tr/th/td` 换成 `view` **只做了一半** ——
`view` 默认 `block`，而原版 CSS 靠 `border-collapse: collapse` + 表格布局排版，
**这套规则对块级 `view` 完全不生效** → 每个单元格各占一行，整表塌成竖排
（管理台日志页 / 授权页 2026-09-22 就中了）。

修法：`.u-tr { display: flex }` + 每列显式 `flex: 0 0 <宽度>`，最后一列 `flex: 1 1 0` 吃掉剩余宽度；
原来写在 `td` 上的 `colspan="8"`（展开行 / 空态行）在 `view` 上无效，改成单格 `flex: 1`。

**两个必踩的坑**：

| 坑 | 现象 | 修法 |
|---|---|---|
| flex 项默认 `min-width: auto` | 列被「最窄内容」撑宽 —— 表头文字短、数据文字长（如级别列的 ERROR 徽标）→ **表头与数据行列宽对不上、整列错位** | 单元格一律加 `min-width: 0` |
| 补完 `min-width: 0` 后，超长文本会溢出压到相邻列上 | 原版真表格列宽随内容自动变宽，`view` + flex 没有这个能力 | 可能超长的列自己截断：`overflow: hidden; text-overflow: ellipsis; white-space: nowrap`，完整值放 `title` |

### ⚠️ 窄屏不许横向滚动条：表格一律降级成卡片（2026-09-23）

> **⏳ 待办（2026-09-23 起）**：本端已改为「只保留移动形态」，但**管理台三页（`admin/index`、`admin/logs`、
> `admin/users`）的桌面表格与 860px 断点尚未清理** —— 它们仍是「桌面表格 + 窄屏降级卡片」的响应式写法。
> 清理方式与其它页面一致（移动态提升为基础态、删断点），留待后续单独处理。
> 在此之前，下面这套「窄屏降级」逻辑仍然有效、不要删。

桌面表格是**固定列宽 + 外层容器横滚**（上一条）。但**窄屏不允许横向滑动条** ——
表格列一多（日志页 8 列固定宽合计 ≈ 944px），可视区只有 ~343px，横滚出来的是一条几乎没法用的细缝。
所以 `@media (max-width: 860px)` 里**整块换成纵向卡片**：

| 页面 | 折叠态（默认） | 展开态（点行） |
|---|---|---|
| `admin/logs` | **时间 · 级别徽标 · 事件** 一行 + 消息（多行，不再截断） | 详情区补齐**源站 / 作品 / 章节 / 页数** + 记录器 / 任务 / 原因 / 接口 / 消息 / 异常堆栈 |
| `admin/users` | 每段「标签 + 值」竖排（用户名 / 昵称 / 角色 / 注册时间 / 操作） | 无（行内已有操作按钮，没有隐藏字段） |

四条通用做法：

1. **根上消除横滚**：`.table-wrap { overflow: visible; max-height: none }`，
   `.user-table { overflow-x: visible }`。⚠️ 只改 `overflow-x: hidden` 是**掩耳盗铃** —— 内容仍超宽，
   会改成**页面级**横滚，一样是横向滑动条。
2. **隐藏表头**（`.u-thead { display: none }`）：卡片每段自带语义，表头无意义。
3. **必须重置列宽**：桌面的 `flex: 0 0 148px` 是**主轴**方向的基准。卡片改纵向后主轴变成**高度** ——
   不重置的话每段会被钉成 148px 高。（日志页卡片仍是横向主轴，但时间列钉死 148px 会把级别/事件挤出去，同样要重置。）
4. **窄屏专用字段用 `.narrow-only` 二选一**，别用「按宽度分流」的脚本判断（见下文顶栏那条）：
   日志页详情区里新增的 4 行（源站/作品/章节/页数）加 `.narrow-only`，宽屏 `display: none` ——
   桌面表格已有这几列，详情区再来一遍是重复。
   ⚠️ `display: none` 那条**必须写在 `@media` 之前**：两条选择器特异性相同，靠源码顺序决出胜负。

**日志页的伸缩展开**：复用原有的 `toggle()` / `.detail-row`（`v-if="expandedId === row.id"`），
模板只加了 4 行 `.kv.narrow-only`，其余全靠一处媒体查询。窄屏展开箭头用 `.row::after` 绝对定位
（`▾` / `.row.open` 时 `▴`），不参与 flex 布局、宽屏 `content` 为 `none`。

**采集管理台（`admin/index`）**：它是卡片不是表格，无需展开；窄屏只要把 `.grid` / `.maint-row` 的
`minmax(360px, 1fr)` 降成 `1fr`。⚠️ **360px 是硬下限**：窄屏内容区不足 360px 时列宽仍按 360px 撑开 ——
实测 393 视口溢出 7px（左右边距 16/9 不对称）、**360 视口直接出整页横向滚动条**（`scrollWidth 376 > clientWidth 352`）。

**实测**（2026-09-23，`docScrollWidth === docClientWidth` 为「无横滚」判据）：

| 页面 | 393×852 | 360×800 | 1280×900 |
|---|---|---|---|
| `admin/logs` | 无横滚；折叠 4 段；展开 9 项 kv + 堆栈 | 无横滚 | 8 列表格原样；`.narrow-only` 全 `display:none`；`::after` 为 `none` |
| `admin/users` | 无横滚；表头隐藏；每格 flex + `.lbl` | — | 表头可见、行 `flex-direction: row`、`.lbl` `display:none`、`.c-user` basis 180px |
| `admin/index` | 无横滚；单列 353px、边距 16/16 | 无横滚；卡片 320px、边距 16/16 | `.grid` 3 列 / `.maint-row` 2 列（与改动前一致） |

## 底栏导航

**主导航固定在底栏**（2026-09-23 起为本端唯一形态，不再有宽窄屏之分）。

| 区域 | 内容 |
|---|---|
| 顶栏左 | **☰ 菜单按钮**（`order: 1` 排到最左）—— 点击从左侧滑出二级菜单 |
| 顶栏中 | 搜索框（吃掉剩余宽度） |
| 顶栏右 | 消息铃铛（**恒为跳独立消息页**）+ **主题切换**（🌙/☀️） |
| 底栏 | 首页 · 最近更新 · 分类（三等分，带图标，选中态变主题橙） |
| 菜单内 | **账号区**（未登录=整宽「登录」按钮 / 已登录=头像+昵称+「退出登录」）+ 全部导航（首页/分类/最近更新/排行/我的收藏与历史/采集管理/授权管理） |

- 顶栏重排靠 **flex `order`**（菜单 1 / 搜索 2 / 消息 3 / 主题 4）、不改 DOM 顺序。
- 桌面专属元素（`.logo` / `.nav-links` / `.logout` / `.login-link` / `.user-chip`）**已从模板删除**，
  **账号入口只在菜单里**。

**改这里时别踩的坑**

- **断点只有 CSS 一处**：**脚本里没有宽度判断**。
  菜单只由 ☰ 触发，不需要「按宽度分流」—— 旧实现里的 `MOBILE_MAX` / `viewportWidth()`（用来判断
  点「用户头像」该展开菜单还是跳页）已随「账号入口收进菜单」一并删除，**别再照抄回来**。
- ⚠️ **消息铃铛现在只有一个**（跳独立页）。原先「宽屏开浮层 / 窄屏跳页」靠两个同形铃铛
  （`.msg-btn.wide-only` / `.narrow-only`）+ CSS 二选一，已随桌面端删除。
  **若将来又要「按宽度分流」，用「两个元素 + CSS 二选一」，不要回到脚本判断宽度** ——
  这样断点仍然只有 CSS 一份，不存在「JS 阈值改了、CSS 忘了改」的漂移。
- **底栏 z-index = 120**：高于内容、低于 toast（999）。
  阅读器是 `position: fixed` + z-index 200 的全屏层，**会盖住底栏** —— 与顶栏（z-index 100）同一处理方式，因此不需要额外排除逻辑。
- **底部安全区**：底栏带 `padding-bottom: env(safe-area-inset-bottom)`；`.page` 补了 `padding-bottom: 84px`
  （写成两条，`env()` 不被支持时回落第一条），否则最后一行会被底栏盖住。

**底栏图标（`src/utils/icons.ts`）**

自绘 SVG，**运行时编码成 base64 data URI** 交给 uni 的 `<image>`：

- 不用裸 `<svg>` 标签 —— 项目约定「模板只用 uni 组件」，`<image>` 三端行为一致。
- 不用 `.svg` 文件 —— `<image>` 对 svg **文件**的支持各端不一致；base64 data URI 最通用。
- 不引图标库 —— 3 个图标不值得加依赖。
- **颜色写死在 SVG 里**（`<image>` 不认 `currentColor`）→ **主题 × 选中态 = 4 份**：
  `TAB_ICONS`（明亮）/ `TAB_ICONS_DARK`（夜间），各含 `off`/`on`；`Layout` 抽了个
  `tabIcon(path, on)` 按 `isDark` + `route.path === t.path` 选 `:src`。夜间那份不能省 —— 默认态
  用的是 `--text-2`，夜间该值变亮，用明亮那套在深底上基本看不见。
- 不用 `btoa`（部分运行环境没有）→ 自带 ASCII 版 base64 编码器（SVG 内容全 ASCII），已与 `Buffer.toString('base64')` 逐字节比对通过。
- ⚠️ `<image>` **必须显式给宽高**（uni 默认 320×240），这里 `.bn-icon { width: 22px; height: 22px }`。

**未验证项**：App 端未实机跑过（需 HBuilderX 打包）；断点与图标在 App 端走同一套 CSS / 组件，理论上一致。

## 漫画列表（封面网格一律 3 列）

2026-09-22 用户要求「移动端每行三部」。**所有封面网格列表统一 3 列**
（2026-09-23 起本端只有移动形态，故不再有桌面列数）：

| 位置 | 类名 | 列数 | ≤560px（手机收紧） |
|---|---|---|---|
| 首页 热门 / 最近更新 / 分类精选 | `index/index.vue` `.grid` | 3 | 3（gap 16→10） |
| 最近更新 | `latest/index.vue` `.grid` | 3 | 3（gap 16→10） |
| 分类 / 搜索 | `search/index.vue` `.grid` | 3 | 3（gap 16→10） |
| 我的收藏 | `me/index.vue` `.fav-grid` | 3 | 3（gap 14→10） |

- ⚠️ **每页条数必须 = 列数 × 行数**（2026-09-23 用户报「第一页最后一行最后一格空掉」）：
  分页页面的 `pageSize` 要能被列数整除，否则末行会留下空格。
  `latest` / `search` 两页取 **`pageSize = 18`** = 3 列 × 6 行，正好填满。
  **别随手改回 20**：20 ÷ 3 = 6 行余 2，末行就空一格。
  （末页是余数页，留不齐属正常，例如分类页第 3 页 16 条 → 末行 1 个。）
- 手机列宽只有 **~110px**（390px 视口，含 16px 页面内边距 + 10px 间距），所以卡片的字号/内边距
  由 **`components/ComicCard.vue` 里的同名 ≤560 断点**统一收紧（标题 13px、作者/最新话 11px、
  角标 10px），作者名补了 `ellipsis`（原先没截断，窄卡片下会撑破行）。**改列数时记得一起看它。**
- **行式列表不适用，别顺手改**：`我的 · 最近阅读`（`.row`，带「读到第 N 页」进度 + 续读/删除按钮）
  与 `排行榜`（`.rank`，带排名序号 + 🔥热度）保持行式 —— 改成封面网格会丢掉这些信息/操作
  （2026-09-22 已与用户确认）。
- ⚠️ **页面左右内边距**：`style.css` 里 `.page { padding: 20px 16px 48px }` 的左右 16px **不能省** ——
  `.page` 与 `.container` 同为单类选择器且 `.page` 在后面，简写 `padding` 会把 `.container` 的 `0 16px`
  整体覆盖成 0，窄屏下网格直接贴屏幕边缘（原 comic-web 同此写法，属移植过来的既有问题，已修）。

## 筛选条（标签 + 排序）

`components/FilterBar.vue` —— **分类浏览（`/search`）与热度排行（`/rank`）共用**的筛选条，
只有这一份：改条件 / 加排序项只改这里，不会两页走样。

- 对外接口：props `{ category, sort, categories }`、emits `update:category` / `update:sort`。
  **调用方不能对它写 `v-model`**（自定义组件红线），一律 `:category` + `@update:category`。
- **标签用下拉（`Picker`）不用 chip 平铺**：库内 30 个标签平铺会占掉整屏、把结果推到下面。
  选项文案带计数（`恋爱（42）`）—— 但 **「全部」不显示数字**：后端给它的 count 是**各标签计数之和**
  （同一部作品挂 3 个标签就计 3 次），与真实作品数不符（实测 119 vs 实际 52），
  显示出来会和排行页的「共 N 部」打架。选项在这里**统一生成**，两页都不再各自拼标签文案。
- 排序三档（`ComicSort`）：`views` 最热 / `favorites` 收藏最多 / `updated` 最新更新。
  **两页默认都是 `views`（热度降序）**。
- 窄屏（393px）下 `.filter-bar` 靠 `flex-wrap` 折成两行（标签一行、排序一行），不需要额外的媒体查询。

**排行页形态**：`/rank` 是**一整条全库榜单**（不再是「每个标签一个区块」），`PAGE_SIZE = 20`，
`onReachBottom` 追加下一页；名次是累计下标（`i + 1`，跨页连续）。切标签 / 切排序都走 `load(true)`
（清空重拉），并用 `reqId` 令牌丢弃过期响应，避免旧请求盖掉新榜。

**后端排序口径**（`crawler-service/.../mysql/comic_store.py` 的 `list_comics`）：
`views` → `heat DESC`；`favorites` → `favorite_count DESC, heat DESC, sync_time DESC`；其余 → `sync_time DESC`。
排序键都带 `c.sync_time DESC, c.id DESC` 兜底，保证**同分时顺序稳定**（否则翻页会重复 / 漏条）。

## 首页区块（每块 3 部 + 「全部」链接）

首页**三类区块一律只放排名最前的 3 部**（`index/index.vue` 的 `TOP_N = 3`）：🔥 热门榜单、⚡ 最新更新、
各 `分类 · 精选`；其余走**区块标题行右侧**的「全部 ›」。

| 区块 | 取数 | 「全部 ›」→ |
|---|---|---|
| 🔥 热门榜单 | `getComics({ sort: 'views', pageSize: 3 })` | `goAll('/rank')` → 排行页（全库热度榜 + 标签/排序筛选） |
| ⚡ 最新更新 | `getComics({ sort: 'updated', pageSize: 3 })` | `goAll('/latest')` → 最近更新页 |
| `X · 精选` | `getComics({ category: X, pageSize: 3 })` | `goCategory(X)` → `/search?category=X`（分类页 `applyQuery()` 读 URL 直达） |

- 链接在 `.section-title` 里，靠 `margin-left: auto` 顶到标题行最右（与容器右边缘对齐）。
- 取数直接传 `pageSize: 3`，**不是**「取 8 条再截断」—— 不多取用不到的数据。
- 网格用 `.grid`（4 列）而**不是原来的 `.grid-5`**：3 张卡在 5 列里会空出 40% 宽度，4 列下
  卡片尺寸与其它区块一致。
- ⚠️ **标题必须包一层 `.st-label`**：`.section-title` 是 flex，裸文本节点是「匿名 flex 项」、
  会被压缩换行 —— 实测 390px 下「⚡ 最新更新」断成「最新更 / 新」两行。所以标题文字要
  `<text class="st-label">`（`flex: 0 0 auto; white-space: nowrap`），并让同行的 `.hint` 先让位
  （`flex: 0 1 auto; min-width: 0; white-space: nowrap`；≤560px 直接 `display: none`，
  否则「标题 + 长提示 + 全部 ›」在 390px 下必然换行）。

## 主题（明亮 / 夜间）

顶栏右侧（搜索框与消息铃铛之后）一个圆形按钮切换，图标 🌙 = 当前明亮（点了进夜间）、☀️ = 当前夜间。

| 环节 | 位置 | 说明 |
|---|---|---|
| 状态 | `utils/theme.ts` | 模块级 `ref`，`useTheme()` 给 `{ theme, isDark, setTheme, toggleTheme }` |
| 持久化 | `storage` 的 `comic_theme` 键 | 未存过时**跟随系统**（H5 用 `prefers-color-scheme`，其它端用 `uni.getSystemInfoSync().theme`） |
| 挂载点 | ①`Layout.vue` 的 `.app-shell`（模板根）②H5 的 `<html>` | ① 三端都生效（CSS 变量继承到整棵子树）；② 让 `html/body/page` 自身背景一起切 |

- 配色全在 `style.css` 的 **`.theme-dark`** 变量组里，**组件里不该再写死表面色**。
  ⚠️ `.theme-dark` 必须排在 `:root` **之后**：两者同为单类权重，靠源码顺序取胜。
- 变量分工：卡片/顶栏/面板/输入框 → `var(--card)`；占位底色、页面底 → `var(--bg)`；
  静默块（灰底小标签）→ `var(--mute)`；再淡一档的表面（表头/行 hover）→ `var(--surface-2)`；
  开关轨道 → `var(--track)`；滚动条 → `var(--scroll-thumb)`。**新增组件样式时按这套选变量，别写 `#fff`。**
- ⚠️ **底栏图标要换第二套**：图标颜色是烘死在 SVG 里的（`<image>` 不认 `currentColor`），
  默认态用的是 `--text-2`，夜间该值变亮 → 不换图标在深底上基本看不见。
  `utils/icons.ts` 因此导出 `TAB_ICONS` / `TAB_ICONS_DARK`，由 `Layout` 按 `isDark` 选用。
- ⚠️ **`.app-shell` 上不能写 `position` / `z-index` / `transform` / `filter`**：任一项都会形成层叠上下文
  或包含块，里面那两个 `position: fixed` 的抽屉/遮罩就压不过外面的底栏了（它们本就为此放在 `.nav` 之外）。
  另外 `min-height: 100vh` 是给小程序兜底 —— 那边 `page` 元素背景不随主题变，靠这层铺满视口。
- ⚠️ **个别带固定底色的徽标仍是浅底**（如管理台的 `.badge.warning`、`.src-tag.real`、`.msg-kind` 的
  来源色块）：它们底色与文字色是**成对写死**的，夜间呈现为「浅底 + 深字」的小色块，可读但不够融合。
  要彻底统一得给每个色块都配一套夜间值，本次未做。

## 漫画明细页（`pages/comic`）

**布局（本端唯一形态）**：卡片保持**横向** —— 封面在**左上**、明细与按钮在**右上**。
刻意**不改成上下堆叠**：堆叠会把封面下方的空间全浪费掉，横向布局一屏能多露出半屏章节。

| 部分 | 现状 |
|---|---|
| `.hero` | 横向 `flex`，padding 14px、gap 12px、`align-items: flex-start`，封面 **96×128 在左上**，明细与按钮进 **右上**（`.hero-info`），标题 17px |
| `.actions` | 并排 + `flex-wrap`（「续读第 N 话」变长时兜底换行），按钮字号 13px |
| `.chapters` | **4 列**（列宽 ~82px），**隐藏 `.no` 序号徽标**（否则吃掉一半宽度），标题居中、12px |

- 章节标题本身就是「第 12 话」这类短语，所以只留标题、不显示序号徽标。
- 卡片下方依次是 `.desc`（描述）与「章节列表」—— 描述块 padding 10/12、13px。
- ⚠️ `.chapters` 的列数是**用真实章节数据量过的**：390px 下 4 列 = 4×82px + 3×8px = 352px，
  正好落在 `.page` 的 16px 内边距里，无横向溢出。
- ⚠️ 原 `@media (max-width: 700px)` 断点（桌面横向大卡 → 移动小卡）**已删除**，
  移动态即基础态。原桌面态（封面 190×253 + 标题 26px + padding 22px）一并移除。

## 消息中心（独立页）

数据源只有一处：`stores/message.ts`（Pinia + 本地持久化，key `comic_msg_notices`，上限 50 条）。
采集 / 巡检 / 自愈任务在后台轮询到 done/failed 时写入，另有 `addSystem()` 预留系统推送。

**本端只有独立页**：点顶栏铃铛 → 跳 `pages/messages/index`（整页：顶部「← 返回 + 全部已读 + 清空」
+ 消息卡片列表）。原先宽屏的顶栏下拉浮层（340px 贴右上角）**已随桌面端删除**。

**已读时机**：**离开时才标已读**（`onHide` + `onUnload` 各挂一次）。若进页就标，顶部「全部已读」按钮
（`v-if="msgStore.unread"`）永远不会出现、未读高亮也看不到 —— 而「哪条是新的」正是未读标记的全部价值。
两个钩子都要挂：`onHide` 覆盖「从抽屉菜单 / 底栏 push 到别的页」（本页只隐藏、不销毁），
`onUnload` 覆盖「返回 / redirectTo」（本页被销毁），漏一个就会角标残留。

- ⚠️ 独立页**必须自带返回入口**：`navigationStyle: custom` 没有原生返回箭头（`login` / `admin/logs` / `reader` 同理）。

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

## 前端问题排查（playwright MCP 实跑取证）

**触发时机**：页面出现**请求报错 / 接口返回不对 / 样式错位 / 交互失效**时，**不必等用户要求**，先在真浏览器里跑一遍再下结论。
**禁止**只读源码就断言「应该是 XX 问题」—— 这类猜测在 uni 编译改写（元素变 `uni-view`、样式运行时 `insertRule` 注入）后经常不成立。

**前提**：`npm run dev:h5` 已在 :5174 跑着；MCP 已在连接器管理页 Trust（改过 `mcp.json` 后需重新 Trust，否则工具会从索引里消失）。

**取证三件套**

| 目的 | 工具 | 关键参数 / 说明 |
|---|---|---|
| 看 JS 报错 / 警告 | `browser_console_messages` | 默认返回全部；先 `browser_navigate` 到目标页，再调它 |
| 看请求清单 | `browser_network_requests` | 列 URL / 方法 / 状态码 / 耗时，可过滤 |
| 看单条请求详情 | `browser_network_request` | 传 index，拿请求头、payload、响应体 |
| 看 DOM 结构 / 找元素 | `browser_snapshot` | 无障碍树，返回可点击的 `ref` |
| 直接算值 / 读全局 | `browser_evaluate` | 跑一段 JS，读 `localStorage`、算布局盒模型等 |

**典型流程**

1. `browser_navigate` 到 `http://localhost:5174/#/<目标路由>`（H5 是 hash 路由）。
2. 需要登录态时先走登录流程；token 落在 `localStorage.comic_web_token`，可 `browser_evaluate` 读出来核对。
3. 复现问题 → 读 `browser_console_messages` 拿报错 → 读 `browser_network_requests` 定位是哪条 `/api/*` 挂了 → `browser_network_request` 看响应体。
4. 样式问题：`browser_snapshot` 或 `browser_evaluate` 读 `getComputedStyle` / `getBoundingClientRect`，别靠肉眼读 CSS 文件推断。

**MCP 不可用时：自动检测 + 补装（不等用户要求）**

**第一步永远是「检测 playwright MCP 是否存在」—— 不要只看某个固定配置文件。**
同一个 MCP 可能由**用户级 / 项目级 / 其他 agent 的配置**提供，只翻 `~/.workbuddy/mcp.json` 会误判成「不存在」而**重复写入**。按这个顺序检测：

1. `ToolSearch` 搜 `mcp__playwright__*`，看是否在工具索引里；
2. 查**连接器列表**里有没有 `playwright`。

**结果 A —— 确实不存在**（索引没有、连接器列表也没有）→ **写入标准配置并安装**

把下面这条**合并**进 `mcpServers`（**只加这一条，不要覆盖其他条目**）：

```json
"playwright": {
  "type": "stdio",
  "command": "npx",
  "args": [
    "-y",
    "@playwright/mcp@latest",
    "--browser=msedge",
    "--output-dir=C:/Users/caimf/.workbuddy/playwright-mcp-out"
  ],
  "disabled": false
}
```

写入位置：**用户级 `~/.workbuddy/mcp.json`**（默认落点；若本项目已有项目级配置且更合适，也可写那里，但**先确认该位置确实没有 playwright 条目**）。

两个参数都是**必需**的：`--browser=msedge`（本机只有 Edge，不指定会去找 Chrome 而失败）；`--output-dir`（不加会把自动命名快照落到工作区根的 `.playwright-mcp/`，污染仓库且不在 `.gitignore` 里）。

安装：**不需要单独 `npm i`** —— `npx -y` 首次运行会自动把 `@playwright/mcp` 拉到 npx 缓存；已用过该 MCP 的机器上通常已缓存，写配置即可。

**结果 B —— 已存在，只是工具不在索引**（刚改过配置，主机把连接置回**待信任**）

→ **配置本身没坏，别重写、别重复添加**。这是正常现象，直接进下一步。

**两种结果的收尾都一样 —— 必须显式提示用户**

WorkBuddy **不会自动启用**新 MCP：需要用户到**连接器管理页右上角「自定义连接器」入口，点 `playwright` 的 Trust**。**这条提示必须打出来，不能省略、不能只在心里想**；Trust 完成后本会话的 `mcp__playwright__*` 才会回到索引。

**Trust 完成前**：不要静默退回「读代码猜」。可先用本机替代手段临时取证（直接 `curl` 打接口看响应、无头浏览器 CDP 脚本、让用户贴控制台截图），并**说明这是临时手段**、已在等 Trust。

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
- **表面色一律走 CSS 变量，禁止再写 `#fff`**：主题（明亮 / 夜间）就是换一套变量值，写死的白底在夜间
  会变成「白底 + 浅字」。对照表见上文「主题（明亮 / 夜间）」；新增组件时按那张表选变量。

**已知残留风险**（详细取舍见 `.workbuddy/memory/2026-09-22.md`）

- `flex gap`（69 处）需 Chrome 84+ / iOS 14.1+：老系统上间距会丢失，**布局不会错乱**。
- `backdrop-filter` 2 处属纯装饰；`min/max/clamp`、CSS `grid`、`sticky` 基线较老，风险低。
- **小程序端尚未在真机 / 微信开发者工具里跑过**（本机无 `appid`）；`manifest.json` 的 `appid` 待填。

---

> 修复过程与验证记录写在 `.workbuddy/memory/YYYY-MM-DD.md`，不进本文件。
