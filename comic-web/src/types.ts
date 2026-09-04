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
  views: number          // 热度（用于榜单排序）
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
