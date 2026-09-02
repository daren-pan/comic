// API 服务层 —— 双通道实现：
//   HTTP 通道：真实后端（api-service，FastAPI），接口签名与架构方案 RESTful 一致；
//   回退通道：本地 mock / localStorage，后端不可达时自动降级，前端体验不中断。
// 内容（漫画/章节/页）+ 用户中心（收藏/历史）均走服务端，uid 匿名标识用户。
import type { CategoryCount, Chapter, Comic, FavoriteEntry, HistoryEntry, PageResult } from '../types'
import { MOCK, getChapterPages as mockPages } from './mockData'

export type ComicSort = 'updated' | 'views'

export interface ComicQuery {
  category?: string
  keyword?: string
  sort?: ComicSort
  page?: number
  pageSize?: number
}

// ================= 匿名用户标识（服务端历史/收藏的归属） =================
const USER_KEY = 'comic_web_user_id'
let _uid: string | null = null

export function getUserId(): string {
  if (_uid) return _uid
  let v = localStorage.getItem(USER_KEY)
  if (!v) {
    v =
      typeof crypto !== 'undefined' && crypto.randomUUID
        ? crypto.randomUUID()
        : `u-${Date.now()}-${Math.random().toString(36).slice(2)}`
    localStorage.setItem(USER_KEY, v)
  }
  _uid = v
  return v
}

// ================= HTTP 通道（真实后端） =================
async function http<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(path, init)
  if (!res.ok) throw new Error(`HTTP ${res.status}: ${path}`)
  const body = await res.json()
  if (body.code !== 0) throw new Error(body.message || 'api error')
  return body.data as T
}

function qs(q: Record<string, unknown>): string {
  const p = new URLSearchParams()
  for (const [k, v] of Object.entries(q)) {
    if (v !== undefined && v !== '' && v !== '全部') p.set(k, String(v))
  }
  return p.toString()
}

const u = () => encodeURIComponent(getUserId())

const httpApi = {
  // ---- 内容 ----
  async getComics(q: ComicQuery = {}): Promise<PageResult<Comic>> {
    return http<PageResult<Comic>>(`/api/comics?${qs({ ...q, page: q.page ?? 1, page_size: q.pageSize ?? 12 })}`)
  },
  async getComic(id: number): Promise<Comic | undefined> {
    return http<Comic>(`/api/comics/${id}`)
  },
  async getChapters(comicId: number): Promise<Chapter[]> {
    return http<Chapter[]>(`/api/comics/${comicId}/chapters`)
  },
  async getChapter(comicId: number, chapterId: number): Promise<Chapter | undefined> {
    const list = await this.getChapters(comicId)
    return list.find((c) => c.id === chapterId)
  },
  async getChapterPages(comicId: number, chapterId: number) {
    return http(`/api/chapters/${chapterId}/pages`)
  },
  async getCategories(): Promise<CategoryCount[]> {
    return http<CategoryCount[]>('/api/categories')
  },

  // ---- 用户中心（服务端） ----
  async getFavorites(): Promise<Comic[]> {
    return http<Comic[]>(`/api/users/${u()}/favorites`)
  },
  async isFavorite(comicId: number): Promise<boolean> {
    const d = await http<{ favorited: boolean }>(`/api/users/${u()}/favorites/${comicId}`)
    return d.favorited
  },
  async toggleFavorite(comicId: number): Promise<boolean> {
    const path = `/api/users/${u()}/favorites/${comicId}`
    const cur = await this.isFavorite(comicId)
    const d = await http<{ favorited: boolean }>(path, { method: cur ? 'DELETE' : 'PUT' })
    return d.favorited
  },
  async getHistory(): Promise<HistoryEntry[]> {
    const items = await http<(HistoryEntry & { comic?: Comic })[]>(`/api/users/${u()}/history`)
    return items.map(({ comicId, chapterId, pageNo, readAt }) => ({ comicId, chapterId, pageNo, readAt }))
  },
  async upsertHistory(entry: Omit<HistoryEntry, 'readAt'>): Promise<void> {
    await http(`/api/users/${u()}/history`, {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(entry),
    })
  },
  async getHistoryWithDetail(): Promise<(HistoryEntry & { comic?: Comic; chapterTitle?: string })[]> {
    return http(`/api/users/${u()}/history`)
  },
  async removeHistory(comicId: number): Promise<void> {
    await http(`/api/users/${u()}/history/${comicId}`, { method: 'DELETE' })
  },
}

// ================= 回退通道（本地 mock + localStorage） =================
const delay = (ms = 200) => new Promise((r) => setTimeout(r, ms))
const FAV_KEY = 'comic_web_favorites'
const HIS_KEY = 'comic_web_history'

function read<T>(key: string, fallback: T): T {
  try {
    const raw = localStorage.getItem(key)
    return raw ? (JSON.parse(raw) as T) : fallback
  } catch {
    return fallback
  }
}
function write(key: string, value: unknown) {
  localStorage.setItem(key, JSON.stringify(value))
}

const mockApi = {
  // ---- 内容 ----
  async getComics(q: ComicQuery = {}): Promise<PageResult<Comic>> {
    await delay()
    const { category, keyword, sort = 'updated', page = 1, pageSize = 12 } = q
    let items = [...MOCK.comics]
    if (category && category !== '全部') items = items.filter((c) => c.category === category)
    if (keyword) {
      const k = keyword.trim().toLowerCase()
      items = items.filter(
        (c) =>
          c.title.toLowerCase().includes(k) ||
          c.author.toLowerCase().includes(k) ||
          c.tags.some((t) => t.toLowerCase().includes(k)),
      )
    }
    items.sort((a, b) =>
      sort === 'views'
        ? b.views - a.views
        : new Date(b.updatedAt).getTime() - new Date(a.updatedAt).getTime(),
    )
    const total = items.length
    const start = (page - 1) * pageSize
    return { items: items.slice(start, start + pageSize), total, page, pageSize }
  },
  async getComic(id: number): Promise<Comic | undefined> {
    await delay(120)
    return MOCK.comics.find((c) => c.id === id)
  },
  async getChapters(comicId: number): Promise<Chapter[]> {
    await delay(120)
    return MOCK.chapters.filter((c) => c.comicId === comicId).sort((a, b) => a.orderNo - b.orderNo)
  },
  async getChapter(comicId: number, chapterId: number): Promise<Chapter | undefined> {
    await delay(80)
    return MOCK.chapters.find((c) => c.comicId === comicId && c.id === chapterId)
  },
  async getChapterPages(comicId: number, chapterId: number) {
    await delay(80)
    return mockPages(comicId, chapterId)
  },
  async getCategories(): Promise<CategoryCount[]> {
    await delay(80)
    const map = new Map<string, number>()
    for (const c of MOCK.comics) map.set(c.category, (map.get(c.category) ?? 0) + 1)
    return [{ name: '全部', count: MOCK.comics.length }, ...[...map.entries()].map(([name, count]) => ({ name, count }))]
  },

  // ---- 用户中心（localStorage） ----
  async getFavorites(): Promise<Comic[]> {
    await delay(100)
    const favs = read<FavoriteEntry[]>(FAV_KEY, [])
    const ids = new Set(favs.map((f) => f.comicId))
    return MOCK.comics.filter((c) => ids.has(c.id))
  },
  async isFavorite(comicId: number): Promise<boolean> {
    return read<FavoriteEntry[]>(FAV_KEY, []).some((f) => f.comicId === comicId)
  },
  async toggleFavorite(comicId: number): Promise<boolean> {
    await delay(60)
    const favs = read<FavoriteEntry[]>(FAV_KEY, [])
    const idx = favs.findIndex((f) => f.comicId === comicId)
    if (idx >= 0) {
      favs.splice(idx, 1)
      write(FAV_KEY, favs)
      return false
    }
    favs.push({ comicId, addedAt: new Date().toISOString() })
    write(FAV_KEY, favs)
    return true
  },
  async getHistory(): Promise<HistoryEntry[]> {
    await delay(100)
    return read<HistoryEntry[]>(HIS_KEY, [])
  },
  async upsertHistory(entry: Omit<HistoryEntry, 'readAt'>): Promise<void> {
    const list = read<HistoryEntry[]>(HIS_KEY, []).filter((h) => h.comicId !== entry.comicId)
    list.unshift({ ...entry, readAt: new Date().toISOString() })
    write(HIS_KEY, list.slice(0, 50))
  },
  async getHistoryWithDetail(): Promise<(HistoryEntry & { comic?: Comic; chapterTitle?: string })[]> {
    const list = await this.getHistory()
    const enriched: (HistoryEntry & { comic?: Comic; chapterTitle?: string })[] = []
    for (const h of list) {
      const comic = MOCK.comics.find((c) => c.id === h.comicId)
      const ch = MOCK.chapters.find((c) => c.id === h.chapterId)
      if (comic) enriched.push({ ...h, comic, chapterTitle: ch?.title })
    }
    return enriched
  },
  async removeHistory(comicId: number): Promise<void> {
    const list = read<HistoryEntry[]>(HIS_KEY, []).filter((h) => h.comicId !== comicId)
    write(HIS_KEY, list)
  },
}

// ================= 合并：HTTP 优先，失败自动回退 =================
type Api = typeof httpApi

function withFallback(primary: Api, fallback: Api): Api {
  const out = {} as Api
  for (const key of Object.keys(primary) as (keyof Api)[]) {
    const p = primary[key]
    const f = fallback[key]
    out[key] = (async (...args: Parameters<typeof p>) => {
      try {
        return await p(...args)
      } catch {
        return f(...args)
      }
    }) as typeof p
  }
  return out
}

export const api = withFallback(httpApi, mockApi)

export const getComics = api.getComics.bind(api)
export const getComic = api.getComic.bind(api)
export const getChapters = api.getChapters.bind(api)
export const getChapter = api.getChapter.bind(api)
export const getChapterPages = api.getChapterPages.bind(api)
export const getCategories = api.getCategories.bind(api)
export const getFavorites = api.getFavorites.bind(api)
export const isFavorite = api.isFavorite.bind(api)
export const toggleFavorite = api.toggleFavorite.bind(api)
export const getHistory = api.getHistory.bind(api)
export const upsertHistory = api.upsertHistory.bind(api)
export const getHistoryWithDetail = api.getHistoryWithDetail.bind(api)
export const removeHistory = api.removeHistory.bind(api)

/** 后端可达性探测（用于 UI 标注当前数据来源） */
export async function backendAlive(): Promise<boolean> {
  try {
    const res = await fetch('/api/health')
    return res.ok
  } catch {
    return false
  }
}
