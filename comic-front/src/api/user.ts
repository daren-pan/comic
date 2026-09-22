// 用户中心接口（认证 / 收藏 / 历史）
// 说明：认证与收藏走登录态（JWT，请求拦截器自动附 token）；历史/最近阅读走匿名 userId（无需登录）。
import type { AuthResult, Comic, HistoryEntry, User } from '../types'
import { getUserId } from './auth'
import { request } from './request'

/** 当前匿名 userId（URL 编码后拼进路径），未登录也恒有值 */
const u = () => encodeURIComponent(getUserId())

// ================= 认证 =================

/**
 * 注册新账号
 * @param username 用户名（唯一）
 * @param password 密码（后端 bcrypt 哈希存储；长度至少 6 位由后端校验）
 * @param nickname 昵称（可空，默认取 username）
 * @returns AuthResult（token + user）；用户名已存在时 reject
 * @see POST /api/auth/register
 */
export function register(username: string, password: string, nickname = ''): Promise<AuthResult> {
  return request<AuthResult>('/api/auth/register', {
    method: 'POST',
    data: { username, password, nickname },
  })
}

/**
 * 登录
 * @param username 用户名
 * @param password 密码
 * @returns AuthResult（token + user）；密码错误时 reject
 * @see POST /api/auth/login
 */
export function login(username: string, password: string): Promise<AuthResult> {
  return request<AuthResult>('/api/auth/login', {
    method: 'POST',
    data: { username, password },
  })
}

/**
 * 获取当前登录用户信息（刷新登录态用；需登录）
 * @returns User（id/username/nickname/createdAt）；未登录或 token 过期时 401 → 拦截器登出
 * @see GET /api/auth/me
 */
export function me(): Promise<User> {
  return request<User>('/api/auth/me')
}

// ================= 收藏（需登录） =================

/**
 * 获取当前用户的收藏漫画列表（按收藏时间倒序）
 * @returns Comic[]；需登录（未登录 401 → 拦截器引导登录）
 * @see GET /api/users/{uid}/favorites
 */
export function getFavorites(): Promise<Comic[]> {
  return request<Comic[]>(`/api/users/${u()}/favorites`)
}

/**
 * 查询某漫画是否已被当前用户收藏（详情页收藏按钮状态）
 * @param comicId 漫画主键 id
 * @returns boolean 是否已收藏；需登录
 * @see GET /api/users/{uid}/favorites/{comicId}
 */
export async function isFavorite(comicId: number): Promise<boolean> {
  const d = await request<{ favorited: boolean }>(`/api/users/${u()}/favorites/${comicId}`)
  return d.favorited
}

/**
 * 切换某漫画的收藏状态（已收藏则取消，未收藏则添加）
 * @param comicId 漫画主键 id
 * @returns boolean 操作后的收藏状态（true=已收藏）
 * @see PUT/DELETE /api/users/{uid}/favorites/{comicId}
 */
export async function toggleFavorite(comicId: number): Promise<boolean> {
  const path = `/api/users/${u()}/favorites/${comicId}`
  const cur = await isFavorite(comicId)
  const d = await request<{ favorited: boolean }>(path, { method: cur ? 'DELETE' : 'PUT' })
  return d.favorited
}

// ================= 历史 / 最近阅读（匿名，无需登录） =================

/**
 * 获取最近阅读记录（精简版：只含 comicId/chapterId/pageNo/readAt）
 * @returns HistoryEntry[]（按 readAt 倒序）；匿名 userId 归属，无需登录
 * @see GET /api/users/{uid}/history
 */
export async function getHistory(): Promise<HistoryEntry[]> {
  const items = await request<(HistoryEntry & { comic?: Comic })[]>(`/api/users/${u()}/history`)
  return items.map(({ comicId, chapterId, pageNo, readAt }) => ({ comicId, chapterId, pageNo, readAt }))
}

/**
 * 写入/更新阅读进度（同一本漫画只保留一条，翻页自动刷新）
 * @param entry 含 comicId/chapterId/pageNo；readAt 由后端生成
 * @see PUT /api/users/{uid}/history
 */
export function upsertHistory(entry: Omit<HistoryEntry, 'readAt'>): Promise<void> {
  return request(`/api/users/${u()}/history`, {
    method: 'PUT',
    data: entry,
  })
}

/**
 * 获取最近阅读记录（带详情：附 comic 完整信息 + 章节标题，用于「我的」页展示）
 * @returns 每条含 HistoryEntry + comic + chapterTitle；匿名无需登录
 * @see GET /api/users/{uid}/history
 */
export function getHistoryWithDetail(): Promise<(HistoryEntry & { comic?: Comic; chapterTitle?: string })[]> {
  return request(`/api/users/${u()}/history`)
}

/**
 * 删除某漫画的阅读历史
 * @param comicId 漫画主键 id
 * @see DELETE /api/users/{uid}/history/{comicId}
 */
export function removeHistory(comicId: number): Promise<void> {
  return request(`/api/users/${u()}/history/${comicId}`, { method: 'DELETE' })
}
