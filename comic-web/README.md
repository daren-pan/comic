# comic-web 前端（Vue 3 + TypeScript + Vite + Pinia）

漫画聚合平台的 **Web SPA** 版：数据来自 `../api-service` 的 REST API，内容由 `../crawler-service` 采集入库。

> ⚠️ **已冻结**：新增功能一律做在 `comic-front`（uni-app 版，多端）；本目录只作**参考实现**，
> 约定与逻辑**不再改动**。

## 页面与路由

| 路由 | 页面 | 说明 |
|---|---|---|
| `/` | 首页 | Banner + 热门榜单 + 最新更新 + 分类精选 |
| `/search` | 分类浏览 / 搜索 | 关键词（标题 / 作者 / 标签）+ 分类筛选 + 排序 + 分页 |
| `/latest` | 最近更新 | 按更新时间的卡片网格（`sort=updated`），卡片带相对时间角标 |
| `/rank` | 排行 | 分类区块（作品数 ≥3）+ 块内按**热度**取前 10，区块滚入视口才懒加载 |
| `/comic/:id` | 详情页 | 封面 / 简介 / 标签 / 来源标注 + 收藏 + 章节列表 |
| `/reader/:comicId/:chapterId` | 在线阅读器 | 双阅读模式（左右滑动 / 竖排连播）、主题切换、设置面板、章节切换、进度记忆续读 |
| `/me` | 我的 | 最近阅读（续读 / 删除）+ 我的收藏 |
| `/login` | 登录 / 注册 | JWT 登录；收藏需登录，历史**登录后归属账号、游客用浏览器匿名 id** |
| `/admin` | 采集管理控制台 | 按源开关 / 触发采集 / **全库失效巡检** / 触发按需导入（**需管理员**：超管与普通管理员都可） |
| `/admin/logs` | 运行日志查询 | 按级别 / 源站 / 事件 / 作品 / 任务 / 关键字 / 时间窗筛（日志已落库 `log_record`）；**需管理员** |
| `/admin/users` | 授权管理 | 用户列表 + 在**普通管理员 ⇄ 普通用户**之间切换；**仅超级管理员**可进 |

三条 `/#/admin*` 路由都挂守卫（`router.ts` 的 `requireRole(superOnly)`）：未登录跳登录页（带 `redirect`）、
进门前向 `/api/auth/me` **复核角色**（角色每请求查库，授权 / 取消立即生效）、角色不够则回首页并留一条消息。

## 模块架构

**API 层**（`src/api/`，axios 单通道，按职责拆子模块）

```
src/api/
├── index.ts      barrel 汇总（组件统一 `import { ... } from '../api'`）
├── request.ts    HTTP 请求层：axios 实例 + 拦截器 + request<T> 剥壳 + backendAlive
├── auth.ts       登录态与匿名身份（纯本地）：token 存取 + auth:changed 广播 + getUserId
├── content.ts    内容接口：漫画 / 章节 / 分页 / 分类（公开）
├── user.ts       用户中心接口：认证 / 收藏（需登录）/ 历史
└── admin.ts      管理台接口：源 / 开关 / 采集 / 巡检 / 任务 / 日志 / 授权（需管理员）
```

- **请求**：请求拦截器自动附 `Authorization: Bearer <token>`；泛型 `request<T>()` 剥掉 `{code, message, data}` 外壳；
  401（token 过期 / 无效）→ 自动 `clearAuth()` + 跳登录页；
- **匿名身份**：`getUserId()` 生成浏览器级匿名 UUID（`comic_web_user_id`），游客的历史无需登录即可用。

**状态（Pinia）**

- `stores/user.ts`：登录态响应式镜像（`token`/`user`、`isLoggedIn`/`isAdmin`/`isSuperAdmin`、`login/register/logout/refresh`）。
  token / user 持久化在 localStorage，api 层 `setAuth`/`clearAuth` 广播 `auth:changed` 事件、store 监听后重读 → 全站同步。
- `stores/message.ts`：**顶栏消息中心**（🔔 未读角标 + 面板 + toast）。轮询放在 store（单例）而非组件 ——
  触发任务后 `trackTask` 占位、每 1.5s 轮询 `getAdminTask`，**离开 `/admin` 页仍会跟踪到结束**；
  已完成消息落 localStorage（上限 50 条），刷新时仍在 running 的标记为「任务已中断」。

**阅读器**（`views/ReaderView.vue`）

- 左右滑动：单张居中、懒加载 + 前后页预加载、点击左右 1/4 区域翻页、`←/→` 键盘翻页；
- 竖排连播：整章所有页垂直拼接连续滚动，滚动位置实时推导当前页；
- 设置面板（阅读模式 / 背景主题）本地持久化；翻页即写进度，续读自动恢复页码。

**图片**：由后端 `/api/covers/{id}`、`/api/images/...` 提供，前端 `utils/images.ts` 生成 SVG data URI 占位图兜底。

## 基础命令

```bash
npm install
npm run dev        # 开发模式 http://localhost:5173（HMR，/api 代理到 8000）
npm run build      # 生产构建 → dist/（base='./'，hash 路由，可离线双击打开）
npm run preview    # 预览构建产物
```

> ⚠️ **本机 `npm` 起不来时的兜底**（例如撞 WSL / 杀软黑名单，报 `npm.ps1 cannot be loaded`）：
> 绕过 npm 直接跑 Vite —— `node ./node_modules/vite/bin/vite.js --host 127.0.0.1 --port 5173`。

| 依赖 | 用途 | 备注 |
|---|---|---|
| vue / vue-router | 框架 + 路由 | hash 路由（`createWebHashHistory`），配合 `base:'./'` 任意静态托管可跑 |
| **pinia** | 登录态 / 消息中心全局共享 | ⚠️ 用 **pinia@2**（pinia@4 要求 TS≥5.6，本项目 TS 5.4） |
| **axios** | HTTP 请求 | 单通道接真实后端；拦截器统一 token / 解包 / 401 |
| typescript | 类型 | 项目无 vue-tsc，类型检查靠 IDE / tsc |

## 约定

- **日常只 `npm run dev`（5173），不构建产物**；只有发布成品才 `npm run build`，由后端同源托管 `dist/`。
- **新增接口**：内容类加到 `api/content.ts`、认证 / 收藏 / 历史加到 `api/user.ts`；方法写显式返回类型
  （`request<返回类型>(...)` + `: Promise<返回类型>` 成对），新领域类型在 `types.ts` 定义并 `import type`。
- **后端不可达时前端报错，不降级 mock**（双通道已移除，数据以真后端为准）。
- 本目录**不再新增功能**（见文件头「已冻结」）——新需求做在 `comic-front`。

---

> 修复过程与验证记录写在 `.workbuddy/memory/YYYY-MM-DD.md`，不进本文件。
