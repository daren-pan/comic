// HTTP 请求层（uni.request 单通道）
// 职责：uni.request 封装 + 自动附 token + 401 统一处理 + 泛型 request<T> 剥壳。
//
// 与 comic-web（axios 版）的**唯一差异**是底层传输换成 uni.request —— 对外签名
// `request<T>(path, {method,data,params})` 与错误语义（errorMessage 取后端中文提示）完全一致，
// 于是 content/user/admin/ondemand 四个业务模块一行都不用改。
//
// 两处 uni 与 axios 的差异已在实现里抹平：
//   1) uni.request 没有 axios 的 `params` 选项 → 本层把 params 序列化进 query string；
//   2) 401 跳登录页：axios 版改 `window.location.hash`，这里改用页面栈 redirectTo（跨端可用）。
import { clearAuth, getToken, isLoggedIn } from './auth'

// 后端统一响应结构 {code, message, data}
interface ApiEnvelope<T> {
  code: number
  message: string
  data: T
}

const TIMEOUT = 10000

/** 把 params 序列化为 query string（跳过空值 / undefined / null） */
function buildQuery(params: unknown): string {
  if (!params || typeof params !== 'object') return ''
  const p = new URLSearchParams()
  for (const [k, v] of Object.entries(params as Record<string, unknown>)) {
    if (v !== undefined && v !== null && v !== '') p.set(k, String(v))
  }
  return p.toString()
}

/**
 * 从错误响应体里取出**能给人看**的一句话。
 *
 * 后端有两套错误形状，必须都认：
 * - FastAPI 的 `HTTPException` → `{"detail": "用户名或密码错误"}`（我们所有业务错误都走这个）；
 * - Pydantic 校验失败 → `{"detail": [{"loc": [...], "msg": "field required"}, ...]}`；
 * - 自家成功信封是 `{code, message}`（错误不走它，但留着兜底）。
 *
 * 为什么值得单独抽出来：原先只读 `data.message`，读不到就退化成 HTTP 状态码文案 ——
 * **后端的中文提示全被吞掉**，用户只看到一句没信息量的 401（2026-09-18 用户就是被这句话误导，
 * 以为"注册失败"，实际是"用户不存在/密码不对"的登录失败）。
 */
function errorMessage(data: unknown, fallback?: string): string {
  const body = (data ?? {}) as { detail?: unknown; message?: unknown }
  const detail = body.detail
  if (typeof detail === 'string' && detail) return detail
  if (Array.isArray(detail)) {
    const msgs = detail
      .map((d) => (d && typeof d === 'object' ? String((d as { msg?: unknown }).msg ?? '') : ''))
      .filter(Boolean)
    if (msgs.length) return msgs.join('；')
  }
  if (typeof body.message === 'string' && body.message) return body.message
  return fallback || '网络错误'
}

/** 当前页面在页面栈里的路由（用于「已在登录页就不重复跳」的判断） */
function currentPageRoute(): string {
  const pages = getCurrentPages()
  const cur = pages.length ? pages[pages.length - 1] : null
  return cur ? `/${cur.route}` : ''
}

/**
 * 401 后引导登录：只在"此前确实带着 token"时才跳（避免匿名历史接口误伤），
 * 且已在登录页则不动（否则会把用户从登录页再跳走）。
 */
function redirectToLogin(redirect: string): void {
  if (currentPageRoute() === '/pages/login/index') return
  const url = `/pages/login/index?redirect=${encodeURIComponent(redirect)}`
  uni.redirectTo({ url, fail: () => uni.navigateTo({ url }) })
}

/**
 * 泛型请求封装：发请求并剥掉后端 {code,msg,data} 外壳，把 data 交给调用方
 * @param T    期望返回的业务数据类型（TS 全程推导）
 * @param path  接口路径（相对路径，如 /api/comics/1）
 * @param init  method（默认 GET）/ data（POST/PUT 请求体）/ params（查询参数）
 * @returns Promise<T>，成功时只含业务 data；业务 code!==0 或 HTTP 错误时 reject
 */
export function request<T>(
  path: string,
  init: { method?: string; data?: unknown; params?: unknown } = {},
): Promise<T> {
  const { data, params, method = 'GET' } = init
  const query = buildQuery(params)
  const url = query ? (path.includes('?') ? `${path}&${query}` : `${path}?${query}`) : path

  // 请求头：有 token 才附 Authorization（匿名历史等接口自然无 header）
  const header: Record<string, string> = { 'Content-Type': 'application/json' }
  const token = getToken()
  if (token) header.Authorization = `Bearer ${token}`

  return new Promise<T>((resolve, reject) => {
    uni.request({
      url,
      method: method as UniApp.RequestOptions['method'],
      data: data as string | AnyObject | ArrayBuffer | undefined,
      header,
      timeout: TIMEOUT,
      success: (res) => {
        const status = res.statusCode
        const body = res.data as ApiEnvelope<T>

        // 401（token 过期/无效）→ 清登录态（广播 auth:changed）→ 跳登录页
        if (status === 401) {
          const logged = isLoggedIn()
          clearAuth()
          if (logged) redirectToLogin('/')
          reject(new Error(errorMessage(body, '登录已过期，请重新登录')))
          return
        }

        // 其它 HTTP 错误 → 透传后端错误文案
        if (status < 200 || status >= 300) {
          reject(new Error(errorMessage(body, `HTTP ${status}`)))
          return
        }

        // 剥壳：自家信封 {code,message,data}
        if (body && typeof body === 'object' && 'code' in body) {
          if (body.code !== 0) {
            reject(new Error(body.message || 'api error'))
            return
          }
          resolve(body.data)
          return
        }
        resolve(body as T) // 非标准结构（如 health 探测）原样返回
      },
      fail: (err) => {
        reject(new Error(err.errMsg || '网络错误'))
      },
    })
  })
}

/**
 * 后端可达性探测（页脚 UI 标注数据来源：真实连接 or 不可达）
 * @returns boolean 后端 /api/health 可达且返回 200
 */
export function backendAlive(): Promise<boolean> {
  return new Promise((resolve) => {
    uni.request({
      url: '/api/health',
      method: 'GET',
      timeout: 3000,
      success: (res) => resolve(res.statusCode === 200 && !!res.data),
      fail: () => resolve(false),
    })
  })
}
