// 领域类型 —— 前端消费的接口契约。
//
// **字段形状的事实来源是后端响应模型**（`api-service/schemas_out.py`）：
// 核心类型直接从 `./api/generated/schema`（`npm run gen:api` 自动生成）提取 ——
// 后端改字段后重跑生成即可，不再手抄（消除「手抄漂移」的根因）。
// 生成是两步：后端 `python tools/export_openapi.py` → 前端 `npm run gen:api`。
import type { components } from './api/generated/schema'

/** OpenAPI 契约里的全部 schema（`components.schemas`） */
type ApiSchemas = components['schemas']

/**
 * 连载状态 —— **规范值只有这四个**（后端的唯一定义处是 `comic_core/status.py`）。
 *
 * 2026-10-13 之前：各源适配器各写一套映射（输出用词互不相同），接口层还用白名单
 * 把认不出的写法**一律改成"连载中"** —— 于是库里 2 部已完结的作品在界面上显示成
 * 「连载中」（54 行里 31 行的状态值不在白名单内）。现在后端统一归一，这里与之一一对应。
 *
 * ⚠️ 新增源若引入新状态词，后端会**原样保留**（不吞、不猜）并记一条 warning；
 * 那种情况下要同步扩这里，否则界面会显示预期外的文本。
 */
export type ComicStatus = '连载中' | '已完结' | '休载' | '已取消'

/**
 * 作品（前台契约）。字段形状**直接来自后端 `ComicOut`**（自动生成），
 * `status` 在本地收窄为 `ComicStatus`（生成版是宽 `string`，见上面对该类型的说明）。
 *
 * 几个非显而易见字段（最终说明以后端 `schemas_out.ComicOut` 为准）：
 * - `cover`：本平台取图端点 `/api/covers/{id}`（不是源站外链、不暴露图床路径）
 * - `heat`：热度分 = 1000（起底）+ 浏览×1 + 收藏×2，用于榜单排序
 * - `updatedAt`：最近更新时间，驱动「最新更新」列表
 * - `source`：该行来自哪个源（**一行 = 一个源**；跨源不合并，同名作品可能各占一行）
 */
export type Comic = Omit<ApiSchemas['ComicOut'], 'status'> & { status: ComicStatus }

/**
 * 章节。字段形状来自后端 `ChapterOut`；
 * `isNew` = 属于「最近一批入库」（详情页右上角"新"角标）。
 */
export type Chapter = ApiSchemas['ChapterOut']

/** 阅读器的一页（`imageUrl` 指向本站取图端点，不暴露源站地址）。字段形状来自后端 `PageOut`。 */
export type PageInfo = ApiSchemas['PageOut']

/**
 * 一条评论（`/api/comics/:id/comments`）。字段形状来自后端 `CommentOut`。
 * `author`：**作者账号已删 = 「已注销用户」**（兜底文案在后端，见 `serializers.to_comment`）。
 */
export type Comment = ApiSchemas['CommentOut']

/**
 * 评论列表 —— 分页壳 + 开关状态（**合并进 `PageResult<T>` 的别名**，2026-10-13）。
 *
 * `enabled` = 全站总开关 AND 单作品开关。**关闭时列表接口照样 200**（只是列表为空），
 * 详情页要能区分「还没有人评论」与「评论区已关闭」—— 所以它不能靠"空列表"猜。
 */
export type CommentPage = PageResult<Comment> & { enabled: boolean }

/**
 * 管理台「作品管理」行 = `Comic` + 三个**治理字段**（只给管理台，前台契约不带）。
 * 字段形状来自后端 `AdminComicOut`；`status` 同 `Comic` 收窄。
 *
 * - `listed`：上架状态（true = 上架；下架后前台立刻不可见，但数据保留）
 * - `commentEnabled`：单作品评论开关（有效值 = 全站总开关 AND 它）
 * - `sourceComicId`：源站作品 ID（「补全章节」按它精确定位，见 pages/admin/comics.vue）
 */
export type AdminComic = Omit<ApiSchemas['AdminComicOut'], 'status'> & { status: ComicStatus }

/** 管理台作品列表 —— **合并进 `PageResult<T>` 的别名**（2026-10-13）。 */
export type AdminComicPage = PageResult<AdminComic>

/**
 * 分页壳 —— **全站统一**（对应后端 `schemas_out.PageResult`）。
 *
 * 2026-10-13 之前有 **5 份形状一字不差**的独立 interface 各写各的
 * （`CommentPage` / `AdminComicPage` / `AdminUserPage` / `LogQueryResult` + 本类型），
 * 加一个字段要改五处。现在它们都是本类型的别名（保留旧名只为不动调用点）。
 */
export interface PageResult<T> {
  items: T[]
  total: number
  page: number
  pageSize: number
}

export interface FavoriteEntry {
  comicId: number
  addedAt: string
}

export interface HistoryEntry {
  comicId: number
  chapterId: number
  pageNo: number
  readAt: string
}

export interface CategoryCount {
  name: string
  count: number
}

export interface User {
  id: number
  username: string
  nickname: string
  role: string              // 'superadmin' 超管（管理台+日志+授权，全库唯一）/ 'admin' 普通管理员（管理台+日志）/ 'user' 普通用户
  avatarUrl?: string        // 上传头像的 URL（'' / 缺省 = 未上传，显示首字母头像；见 components/UserAvatar.vue）
  createdAt: string
}

export interface AuthResult {
  token: string
  user: User
}

// ---------------- 采集管理（运维控制台） ----------------
export interface SourceInfo {
  name: string
  enabled: boolean
  priority: string          // primary / backup
  interval: number          // 增量轮询间隔（秒）
  comicCount: number        // 库内该源作品数
  lastSync: string | null   // 上次同步完成时间（ISO）
}

/**
 * 管理台「定时任务」配置（`/api/admin/schedule`）。
 *
 * 节奏用 **5 段 cron**（`分 时 日 月 周`）表达 —— 「每天定点」与「每隔一段时间」已合并成一个表达式，
 * 例如每天 03:00 是 `0 3 * * *`、每周一 03:00 是 `0 3 * * 1`；「每隔 N 分钟」用步长形式表达。
 * ⚠️ 本注释刻意不写那种步长的字面量：`星号斜杠N` 里的两个字符会**提前闭合块注释**（踩过两次）。
 * 完整写法见页面上的预设按钮与 `comic-scheduler/README.md`。
 * 每轮对 `sources` 里每个源执行一次采集（`mode`/`limit`/`since` 与「触发采集」同一套参数）。
 * ⚠️ `sources` 留空 = 全部「**代码里默认启用**」的源；定时任务**不看**数据源开关。
 */
export interface AdminScheduleConfig {
  enabled: boolean
  cron: string                 // 5 段 cron：分 时 日 月 周（语义校验在后端）
  action: 'sync' | 'inspect'   // 这一轮干什么：逐源采集 / 失效巡检
  sources: string[]            // 空 = 全部「代码里默认启用」的源（巡检时为全库）
  mode: 'incremental' | 'full' // 仅 action='sync' 有意义
  limit: number | null         // 受控样本数；null = 不限（仅 action='sync' 有意义）
  since: string | null         // 时间窗下界（ISO）；巡检时作为转存窗口下界
}

/** 定时任务状态：配置 + 本轮实际源 + 下次执行时刻 + 最近一次运行结果（+ 执行器在线情况）。 */
export interface AdminScheduleStatus {
  config: AdminScheduleConfig
  sources: string[]            // 后端算出的本轮实际源（配置留空时的默认集）
  nextRunAt: string | null     // 下次执行（ISO，**严格晚于当前**）；未启用/表达式非法为 null
  serverTime: string           // 服务器当前时间（对齐时区用）
  running: boolean
  lastRunAt: string | null
  lastStatus: 'running' | 'done' | 'failed' | null
  lastMessage: string | null
  lastTaskId: string | null
  lastSources: string[]
  cronError: string | null     // 表达式非法时的原因（配置文件被手改坏时才会出现）
  executorAlive: boolean       // 执行器（独立进程 comic-scheduler）心跳是否新鲜
  heartbeatAt: string | null   // 执行器最近一次心跳；没有它说明执行器从没起来过
  executorPid: number | null   // 执行器进程号（运维排查用）
}

/** 「立即执行一次」的返回：只是"**请求已提交**" —— 采集在独立进程里跑，api 拿不到任务号。 */
export interface AdminScheduleRunNowResult {
  requested: boolean
  requestedAt?: string
}

export interface SyncStats {
  source: string
  mode: string
  started_at: string
  total_seen: number
  new_comics: number
  updated_comics: number
  new_chapters: number
  failed: number
}

/**
 * 管理台后台任务（`admin_task` 表，`/api/admin/tasks`）。
 *
 * ⚠️ 任务**落库**（2026-10-06 从进程内 dict 搬来）：api 重启不丢、且与**触发账号**绑定
 * （`userId`/`username`），所以能看出"这条是谁点的"。`params` 是触发时的入参快照。
 */
export interface AdminTask {
  id: string
  type: 'sync' | 'transfer' | 'inspect' | 'heal' | 'import' | 'schedule'
  status: 'running' | 'done' | 'failed'
  message: string
  result: Record<string, unknown> | null
  params: Record<string, unknown> | null   // 入参快照（源/模式/limit…）
  userId: number | null                    // 触发账号（定时执行没有账号，故可能为 null）
  username: string
  startedAt: string
  finishedAt: string | null
}

/** 运行日志（`log_record` 表）—— 管理台「日志查询」页 */
export interface LogRecord {
  id: number
  createdAt: string
  level: string
  logger: string
  message: string
  taskId: string
  taskType: string
  excType: string
  source: string
  comicId: number | null
  comicTitle: string
  chapterId: number | null
  chapterTitle: string
  endpoint: string
  pages: number | null
  reason: string
  event: string
  excText?: string       // 只有详情接口带（列表接口不带堆栈全文）
}

export interface LogQuery {
  level?: string
  source?: string
  event?: string
  taskId?: string
  comicId?: number | null
  keyword?: string
  since?: string         // yyyy-MM-dd
  until?: string         // yyyy-MM-dd（含当天）
  page?: number
  pageSize?: number
}

/** 日志查询结果 —— **合并进 `PageResult<T>` 的别名**（2026-10-13）。 */
export type LogQueryResult = PageResult<LogRecord>

/** 日志查询页的筛选候选值 */
export interface LogOptions {
  levels: string[]
  events: string[]
}

/**
 * 下拉选项（`Picker` 组件用）——`value` 是绑定值、`label` 是展示文案。
 *
 * 为什么需要它：uni 没有 `<select>` 对应物，统一改用 `<picker mode="selector">`，
 * 而 picker 只认「字符串数组 + 下标」。这个结构把「下标 ↔ 业务值」的换算收敛在
 * `components/Picker.vue` 里，页面只提供 `{value,label}[]`，逻辑与 comic-web 保持一致。
 */
export interface PickerOption {
  value: string | number
  label: string
}

// ---------------- 源站搜索 / 按需导入 ----------------
export interface SourceSearchItem {
  source: string
  sourceComicId: string
  title: string
  author: string
  cover: string
  status: string
  latestChapterTitle: string
  tags: string[]
  /** 非 null = 库内已收录，可直接打开（原来还有个 `inLibrary` 布尔，与它语义完全重复，已删除） */
  comicId: number | null
}

export interface SourceSearchGroup {
  source: string
  items: SourceSearchItem[]
}

export interface ImportResult {
  comicId: number
  title: string
  author: string
  source: string
  sourceComicId: string
  isNew: boolean
  chapters: number          // 库内现有章节总数
  newChapters: number
  failed: number
  alreadySameSource: boolean  // 本源此前已收过（幂等重复导入；别的源收过是另一行）
  summary: string
}

// ---------------- 授权页（仅超级管理员） ----------------
export interface AdminUser {
  id: number
  username: string
  nickname: string
  role: string              // 'superadmin' / 'admin' / 'user'
  createdAt: string
}

/** 授权页用户列表 —— **合并进 `PageResult<T>` 的别名**（2026-10-13）。 */
export type AdminUserPage = PageResult<AdminUser>

/**
 * 消息中心的一条消息（`message` 表，`/api/messages`）
 *
 * 面向**所有登录用户**：服务端按"这条消息发给谁"（`toUserId` 定向某人 + `minRole` 最低角色）
 * 过滤后再返回，所以同一次请求对不同账号内容不同；**已读按账号各一份**。
 *
 * ⚠️ 列表里有两种条目：
 *   - **已发生的消息**（`id = "msg-<数字>"`，`messageId` 有值）—— 库里的一行；
 *   - **正在跑的任务**（`id = 任务号`，`messageId = null`）—— 还没"发生完"，由后端临时并入
 *     （**仅管理员及以上**：任务消息是管理员范围的）。
 */
export interface MessageItem {
  id: string                                        // 列表 key：消息用 msg-<数字>，运行中的任务用任务号
  messageId: number | null                          // 标记已读用的数字 id（运行中的任务为 null）
  kind: 'sync' | 'transfer' | 'inspect' | 'heal' | 'import' | 'schedule' | 'system' | string
  level: 'info' | 'warn' | 'error'                  // 完成 / 警告 / 失败
  title: string
  body: string
  /**
   * **入参快照**（任务类消息有）：`since`/`until`/`mode`/`limit`/`sources`/`action`/`keyword`…
   *
   * 用途：一眼看出"这条消息说的是**哪段时间范围内**的数据"（`since` = 起始时间，
   * 为空表示"按源自身水位"或"不限"）。列表里由 `paramSummary()` 渲染成一行。
   */
  params: Record<string, unknown> | null
  taskId: string                                    // 关联任务号（可空）
  source: string                                    // 数据源（可空）
  username: string                                  // 触发人（定时轮次 = 系统（定时））
  minRole: '' | 'user' | 'admin' | 'superadmin' | string   // 收件范围：最低角色要求（空 = 所有登录用户）
  status: 'running' | 'done' | 'failed'
  time: string | null
  read: boolean
}

/** 消息列表 + 未读数（`GET /api/messages`） */
export interface MessageFeed {
  items: MessageItem[]
  unread: number
}
