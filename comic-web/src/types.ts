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
  sources: string[]      // 数据来源（体现多源聚合）
  tags: string[]
}

export interface Chapter {
  id: number
  comicId: number
  title: string
  pageCount: number
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
  type: 'sync' | 'transfer' | 'inspect'
  status: 'running' | 'done' | 'failed'
  message: string
  result: Record<string, unknown> | null
  startedAt: string
  finishedAt: string | null
}
