// 内容接口（漫画 / 章节 / 分页 / 分类）—— 公开只读数据，无需登录
import type { CategoryCount, Chapter, Comic, PageInfo, PageResult } from '../types'
import { request } from './request'

export type ComicSort = 'updated' | 'views'

export interface ComicQuery {
  category?: string
  keyword?: string
  sort?: ComicSort
  page?: number
  pageSize?: number
}

/** 查询参数序列化为 query string（跳过空值 / undefined / '全部'） */
function qs(q: Record<string, unknown>): string {
  const p = new URLSearchParams()
  for (const [k, v] of Object.entries(q)) {
    if (v !== undefined && v !== '' && v !== '全部') p.set(k, String(v))
  }
  return p.toString()
}

/**
 * 分页查询漫画列表（首页 / 搜索共用）
 * @param q.category 分类名（'全部' 视为不过滤）
 * @param q.keyword  关键词（匹配标题 / 作者 / 标签）
 * @param q.sort     排序：updated=最新更新 / views=最热
 * @param q.page     页码（默认 1）
 * @param q.pageSize 每页条数（默认 12）
 * @returns 分页结果 PageResult<Comic>
 * @see GET /api/comics
 */
export function getComics(q: ComicQuery = {}): Promise<PageResult<Comic>> {
  return request<PageResult<Comic>>(`/api/comics?${qs({ ...q, page: q.page ?? 1, page_size: q.pageSize ?? 12 })}`)
}

/**
 * 获取单部漫画详情（详情页基础数据；查无此书时后端抛 404）
 * @param id 漫画主键 id
 * @returns Comic（标题/作者/简介/封面/标签等）；后端 404 时 reject
 * @see GET /api/comics/{id}
 */
export function getComic(id: number): Promise<Comic | undefined> {
  return request<Comic>(`/api/comics/${id}`)
}

/**
 * 获取某部漫画的全部章节（按 orderNo 升序）
 * @param comicId 漫画主键 id
 * @returns Chapter[]（每章含 id/title/orderNo 等）
 * @see GET /api/comics/{comicId}/chapters
 */
export function getChapters(comicId: number): Promise<Chapter[]> {
  return request<Chapter[]>(`/api/comics/${comicId}/chapters`)
}

/**
 * 从章节列表中查找指定章节（章节数据来自 getChapters，不在单独接口）
 * @param comicId   漫画主键 id
 * @param chapterId 章节主键 id
 * @returns Chapter | undefined（未找到时返回 undefined）
 */
export function getChapter(comicId: number, chapterId: number): Promise<Chapter | undefined> {
  return getChapters(comicId).then((list) => list.find((c) => c.id === chapterId))
}

/**
 * 获取某章节的分页图片列表（阅读器加载用）
 * @param comicId   漫画主键 id
 * @param chapterId 章节主键 id
 * @returns PageInfo[]（每页含 pageNo/imageUrl/width/height）
 * @see GET /api/chapters/{chapterId}/pages
 */
export function getChapterPages(comicId: number, chapterId: number): Promise<PageInfo[]> {
  return request<PageInfo[]>(`/api/chapters/${chapterId}/pages`)
}

/**
 * 获取分类标签及各自作品数（顶部导航 / 分类筛选）
 * @returns CategoryCount[]（首项恒为「全部」，其后按分类聚合计数）
 * @see GET /api/categories
 */
export function getCategories(): Promise<CategoryCount[]> {
  return request<CategoryCount[]>('/api/categories')
}
