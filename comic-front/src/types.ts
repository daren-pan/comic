// 领域类型 —— 与后端采集服务表结构对应：
// comic / chapter / page（见 crawler-service/src/comic_crawler/models.py）

export type ComicStatus = '连载中' | '已完结'

export interface Comic {
  id: number
  title: string
  author: string
  category: string
  status: ComicStatus
  description: string
  cover: string          // 封面（svg data uri 或 url）
  latestChapterTitle: string
  chapterCount: number
  views: number          // 累计浏览次数（原始计数）
  favoriteCount: number  // 收藏人数
  heat: number           // 热度分 = 1000（起底）+ 浏览×1 + 收藏×2，用于榜单排序
  updatedAt: string      // 最近更新，驱动"最新更新"列表
  source: string         // 该行来自哪个源（一行=一个源；跨源不合并，同名作品可能各占一行）
  tags: string[]
}

export interface Chapter {
  id: number
  comicId: number
  title: string
  orderNo: number
  createdAt: string
}

export interface PageInfo {
  pageNo: number
  imageUrl: string       // 懒加载占位：svg data uri
  width: number
  height: number
}

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

export interface AdminTask {
  id: string
  type: 'sync' | 'transfer' | 'inspect' | 'heal' | 'import'
  status: 'running' | 'done' | 'failed'
  message: string
  result: Record<string, unknown> | null
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

export interface LogQueryResult {
  items: LogRecord[]
  total: number
  page: number
  pageSize: number
}

/** 日志查询页的筛选候选值 */
export interface LogOptions {
  levels: string[]
  events: string[]
}

/**
 * 下拉选项（跨端 `Picker` 组件用）——`value` 是绑定值、`label` 是展示文案。
 *
 * 为什么需要它：小程序**没有 `<select>` 组件**，统一改用 uni 的 `<picker mode="selector">`，
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
  comicId: number | null   // 非 null = 库内已收录，可直接打开
  inLibrary: boolean
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

export interface AdminUserPage {
  items: AdminUser[]
  total: number
  page: number
  pageSize: number
}
