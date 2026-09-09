# comic-web 前端（Vue 3 + TypeScript + Vite + Pinia）

漫画聚合阅读平台的**前端实现**（架构方案见 `../漫画聚合网站_架构设计方案.md`，数据来自 `../api-service` 提供的 REST API，内容由 `../crawler-service` 采集服务入库）。

## 页面与路由

| 路由 | 页面 | 说明 |
|---|---|---|
| `/` | 首页 | Banner + 热门榜单 + 最新更新 + 分类精选 |
| `/search` | 搜索 | 关键词（标题/作者/标签）+ 分类筛选 + 最新/最热排序 + 分页 |
| `/comic/:id` | 详情页 | 封面/简介/标签/多源标注 + 收藏 + 章节列表 |
| `/reader/:comicId/:chapterId` | 在线阅读器 | 双阅读模式（左右滑动/竖排连播）、主题切换、设置面板、章节切换、进度记忆续读 |
| `/me` | 我的 | 最近阅读（续读/删除）+ 我的收藏 |
| `/login` | 登录/注册 | JWT 登录，收藏需登录，历史匿名 |
| `/admin` | 采集管理控制台 | 手动跑采集/懒转存、每源开关、按参数控制范围、历史消息（**无需登录**，运维用） |

## 架构要点

### API 层（`src/api/`，axios 单通道，按职责拆分子模块）

```
src/api/
├── index.ts      barrel 汇总（组件统一 `import { ... } from '../api'`）
├── request.ts    HTTP 请求层：axios 实例 + 拦截器 + request<T> 剥壳 + backendAlive
├── auth.ts       登录态与匿名身份（纯本地）：token 存取 + auth:changed 事件广播 + getUserId
├── content.ts    内容接口：漫画/章节/分页/分类（公开，无需登录）
├── user.ts       用户中心接口：认证/收藏（需登录）/历史（匿名）
└── admin.ts      采集管理接口：源列表/开关/触发采集/触发懒转存/任务状态（运维，无需登录）
```

- **请求**：`request.ts` 统一 `axios` 实例 + **请求拦截器**（自动附 `Authorization: Bearer <token>`）+ **响应拦截器**；
- **解包**：泛型 `request<T>()` 剥掉后端 `{code, message, data}` 外壳，只把 `data` 交给组件（TS 泛型全程推导）；
- **401 处理**：token 过期/无效 → 拦截器自动 `clearAuth()`（广播 `auth:changed` 事件同步 Pinia）+ 跳转登录页；
- **接口签名**与后端 RESTful 一一对应（`getComics`↔`GET /api/comics`、`getChapterPages`↔`GET /api/chapters/{id}/pages`），组件层不感知请求实现；
- **匿名历史**：`auth.ts` 的 `getUserId()` 生成浏览器级匿名 UUID（`comic_web_user_id`），最近阅读/历史无需登录即可跨页使用。

### 登录态（Pinia，`src/stores/user.ts`）

- **store**：登录态响应式内存镜像（state `token/user`、getter `isLoggedIn`、actions `login/register/logout/init`）；
- **持久化**：token/user 落在 localStorage（`comic_web_token`/`comic_web_user`），刷新不丢；
- **事件同步**：api 层 `setAuth`/`clearAuth` 广播 `window` 自定义事件 `auth:changed`，store `init()` 监听后从 localStorage 重读 → 全站组件（顶栏/收藏/书架）实时同步，无路由 hack；
- **分工**：api 层管"数据 + 持久化真相"，store 管"共享 + 响应式"，两者单向依赖无循环。

### 阅读器（架构方案 §4.2）

- **左右滑动**：单张居中、懒加载 + 前后页预加载、点击左右 1/4 区域翻页、`←/→` 键盘翻页；
- **竖排连播**：整章所有页垂直拼接连续滚动，滚动位置实时推导当前页；
- **设置面板**：阅读模式 + 背景主题本地持久化（`comic_reader_settings`）；
- **进度记忆**：翻页即 `upsertHistory` 写入后端，续读自动恢复上次页码。

### 图片

封面与分页图由后端 `/api/covers/{id}`、`/api/images/...` 提供（真实图片已落盘 image_store）；前端 `utils/images.ts` 生成 SVG data URI 占位图兜底（后端不可达/图缺失时展示）。

## 本地运行

前置：后端 8000 已在运行（`api-service`，MySQL 数据）。前端接口统一相对路径 `/api/*`，由 Vite proxy 转发到 `127.0.0.1:8000`。

```bash
npm install
npm run dev        # 开发模式 http://localhost:5173（HMR，/api 代理到 8000）
npm run build      # 生产构建 → dist/（base='./'，hash 路由，可离线双击打开）
npm run preview    # 预览构建产物
```

## 依赖说明

| 依赖 | 用途 | 备注 |
|---|---|---|
| vue / vue-router | 框架 + 路由 | hash 路由（`createWebHashHistory`），配合 `base:'./'` 任意静态托管可跑 |
| **pinia** | 登录态全局共享 | ⚠️ 用 **pinia@2**（pinia@4 要求 TS≥5.6，本项目 TS 5.4） |
| **axios** | HTTP 请求 | 单通道接真实后端；拦截器统一 token / 解包 / 401 |
| typescript | 类型 | 项目无 vue-tsc，类型检查靠 IDE/tsc |

## 开发约定

- **日常只用 `npm run dev`（5173）**，不构建产物；只有发布成品时才 `npm run build`，由后端同源托管 `dist/`。
- **新增接口**：按业务选文件加函数——内容类加到 `api/content.ts`、认证/收藏/历史加到 `api/user.ts`；方法写显式返回类型（`request<返回类型>(...)` + `: Promise<返回类型>` 成对），需要新领域类型时在 `types.ts` 定义并 `import type`。后端不可达时前端会报错而非降级 mock（已移除双通道，数据以真后端为准）。
