// 登录态与匿名身份（纯本地，无网络请求）
// 职责：token/user 的 localStorage 持久化真相 + JWT 有效性判断 + 登录态变更事件广播。
// 说明：api 层只管「持久化真相 + 广播」，Pinia user store 监听 AUTH_EVENT 同步内存镜像。
import type { AuthResult, User } from '../types'

const TOKEN_KEY = 'comic_web_token'
const USER_KEY_STORE = 'comic_web_user'
let _token: string | null = null
let _me: User | null = null

/** 登录态变更事件名（Pinia user store 监听此事件同步内存态，避免 api↔store 循环依赖） */
export const AUTH_EVENT = 'auth:changed'

/** 广播登录态变更事件（setAuth / clearAuth 后触发，store 据此重读） */
function broadcastAuthChanged(): void {
  window.dispatchEvent(new CustomEvent(AUTH_EVENT))
}

/**
 * 读取当前 token（内存缓存 + localStorage 持久化）
 * @returns token 或 null（未登录）
 */
export function getToken(): string | null {
  if (_token) return _token
  _token = localStorage.getItem(TOKEN_KEY)
  return _token
}

/**
 * 写入登录态（登录/注册成功后调用）：token + user 落 localStorage，并广播 auth:changed
 * @param result 后端返回的 AuthResult（含 token 与 user）
 */
export function setAuth(result: AuthResult): void {
  _token = result.token
  _me = result.user
  localStorage.setItem(TOKEN_KEY, result.token)
  localStorage.setItem(USER_KEY_STORE, JSON.stringify(result.user))
  broadcastAuthChanged()
}

/** 解析 JWT 的 payload（第2段），失败返回 null。用于判断过期/有效性。 */
function decodeJwtPayload(token: string): Record<string, unknown> | null {
  try {
    const part = token.split('.')[1]
    if (!part) return null
    // base64url → 归一化 padding 后解码
    const b64 = part.replace(/-/g, '+').replace(/_/g, '/')
    const padded = b64 + '='.repeat((4 - (b64.length % 4)) % 4)
    const json = decodeURIComponent(
      atob(padded)
        .split('')
        .map((c) => '%' + c.charCodeAt(0).toString(16).padStart(2, '0'))
        .join(''),
    )
    return JSON.parse(json) as Record<string, unknown>
  } catch {
    return null
  }
}

/**
 * 判断 token 是否有效（未过期）
 * - 无 token → false
 * - 三段式 JWT：解析第 2 段 exp，当前时间 < exp 才有效
 * - 非 JWT（历史遗留 / 自定义 token）→ 不做过期判断，视为有效
 * @param token 要校验的 token（可传 getToken() 结果）
 * @returns boolean 是否有效
 */
export function isTokenValid(token: string | null): boolean {
  if (!token) return false
  const parts = token.split('.')
  // 非三段式 → 不判断过期，视为有效
  if (parts.length !== 3) return true
  const payload = decodeJwtPayload(token)
  if (!payload) return false
  const exp = Number(payload.exp)
  if (!Number.isFinite(exp)) return false
  // exp 为 token 的过期时刻（绝对时间戳），当前时间 >= exp 则判定过期
  return Date.now() / 1000 < exp
}

/**
 * 清除登录态（登出 / token 过期 401 时调用）：清空 localStorage，并广播 auth:changed
 */
export function clearAuth(): void {
  _token = null
  _me = null
  localStorage.removeItem(TOKEN_KEY)
  localStorage.removeItem(USER_KEY_STORE)
  broadcastAuthChanged()
}

/**
 * 是否已登录 = 存在 token 且未过期
 * （防止残留旧 token 导致误判已登录）
 */
export function isLoggedIn(): boolean {
  return isTokenValid(getToken())
}

/**
 * 读取当前登录用户（内存缓存优先，回退 localStorage）
 * @returns User | null（未登录）
 */
export function currentUser(): User | null {
  if (_me) return _me
  try {
    return JSON.parse(localStorage.getItem(USER_KEY_STORE) || 'null')
  } catch {
    return null
  }
}

// ================= 匿名用户标识（服务端历史/收藏的归属） =================
const USER_KEY = 'comic_web_user_id'
let _uid: string | null = null

/**
 * 获取本机匿名用户标识（首次生成 UUID 并持久化，之后恒同）
 * - 用途：历史/最近阅读的后端归属（无需登录即可用）
 * - 注意：换浏览器/清本机存储会生成新 id（历史随本机，不跨设备）
 * @returns 匿名 id 字符串
 */
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
