// HTTP 请求层（axios 单通道）
// 职责：axios 实例 + 请求拦截器（自动附 token）+ 响应拦截器（401 统一处理）+ 泛型 request<T> 剥壳。
import axios from 'axios'
import { clearAuth, getToken, isLoggedIn } from './auth'

// 后端统一响应结构 {code, message, data}
interface ApiEnvelope<T> {
  code: number
  message: string
  data: T
}

/** axios 单实例：全局超时 10s；URL 用相对路径 /api/xx（dev 由 Vite 代理，prod 同源托管） */
const service = axios.create({
  timeout: 10000,
})

/**
 * 请求拦截器：每个请求自动附加 Authorization: Bearer <token>
 * （有 token 才附；匿名历史等接口自然无 header，登录态接口无需手动带）
 */
service.interceptors.request.use((config) => {
  const token = getToken()
  if (token) config.headers.Authorization = `Bearer ${token}`
  return config
})

/**
 * 响应拦截器（错误分支）：
 * - 401（token 过期/无效）→ 清登录态（广播 auth:changed）→ 跳登录页（仅当此前确实带 token，避免匿名历史接口误伤）
 * - 其它 HTTP 错误 → 透传后端 message（如 {detail: "..."} 或后端业务 message）
 * 成功响应不在此剥壳（需保持 AxiosResponse 类型），解包统一在 request() 泛型封装里做。
 */
service.interceptors.response.use(
  (res) => res,
  (err: { response?: { status?: number; data?: { message?: string } }; message?: string }) => {
    const status = err.response?.status
    if (status === 401) {
      const logged = isLoggedIn()
      clearAuth()
      // 只在"此前确实带着 token"时才跳转登录页，避免匿名历史接口误伤
      if (logged && !window.location.hash.startsWith('#/login')) {
        const redirect = encodeURIComponent(window.location.hash.replace(/^#/, '') || '/')
        window.location.hash = `#/login?redirect=${redirect}`
      }
    }
    return Promise.reject(new Error(err.response?.data?.message || err.message || '网络错误'))
  },
)

/**
 * 泛型请求封装：发请求并剥掉后端 {code,msg,data} 外壳，把 data 交给调用方
 * @param T    期望返回的业务数据类型（TS 全程推导）
 * @param path  接口路径（相对路径，如 /api/comics/1）
 * @param init  method（默认 GET）/ data（POST/PUT 请求体）/ params（查询参数）
 * @returns Promise<T>，成功时只含业务 data；业务 code!==0 或 HTTP 错误时 reject
 */
export async function request<T>(
  path: string,
  init: { method?: string; data?: unknown; params?: unknown } = {},
): Promise<T> {
  const { data, params, method = 'GET' } = init
  const res = await service.request<ApiEnvelope<T>>({
    url: path,
    method,
    data,
    params,
  })
  const body = res.data
  if (body && typeof body === 'object' && 'code' in body) {
    if (body.code !== 0) throw new Error(body.message || 'api error')
    return body.data
  }
  return body as T // 非标准结构（如 health 探测）原样返回
}

/**
 * 后端可达性探测（页脚 UI 标注数据来源：真实连接 or 不可达）
 * @returns boolean 后端 /api/health 可达且返回 200
 */
export async function backendAlive(): Promise<boolean> {
  try {
    const res = await axios.get('/api/health', { timeout: 3000 })
    return !!res.data && res.status === 200
  } catch {
    return false
  }
}
