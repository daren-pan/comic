// 路由兼容层 —— 让 comic-web 的页面代码「约定与逻辑不变」地迁到 uni-app。
//
// 底层是 uni 的页面栈导航（pages.json + uni.navigateTo/redirectTo），对外暴露
// 与 vue-router 同形的 `useRoute()` / `useRouter()`，于是页面里的
// `router.push('/comic/3')`、`route.path` 等写法可以原样保留。
//
// 与 vue-router 的两点差异（**已在 comic-front/README.md 记录**）：
//   1) 参数获取：页面统一用 uni 的 `onLoad(options)` 取参数（uni 惯例），
//      本模块的 `route` 只承载「当前路径 + 查询参数」，供顶栏高亮 / 查询页读取。
//   2) 同页查询变更（如搜索页改筛选）：uni 不允许 navigateTo 自身 →
//      H5 下用 history.replaceState 同步地址栏，其他端为纯本地状态（行为可用）。

import { reactive } from 'vue'

// 同 vue-router：`path` 可省略 —— `{ query }` 表示「在**当前路径**上改查询」（分类页的
// 筛选 / 搜索就是这么调的）；`{ path, query }` 才是跳别的页。别把它写成必填。
export type NavTarget = string | { path?: string; query?: Record<string, unknown> }

export interface RouteState {
  path: string
  fullPath: string
  query: Record<string, string>
}

export const route = reactive<RouteState>({ path: '/', fullPath: '/', query: {} })

/** 同 vue-router：返回当前路由（只读使用） */
export function useRoute(): RouteState {
  return route
}

/** 页面 onLoad 里调用：登记该页面对应的 web 路径 + 查询参数 */
export function setRoute(path: string, query: Record<string, unknown> = {}): void {
  route.path = path
  const q: Record<string, string> = {}
  for (const k of Object.keys(query)) {
    const v = query[k]
    if (v !== undefined && v !== null && v !== '') q[k] = String(v)
  }
  route.query = q
  const qs = Object.keys(q).map((k) => `${k}=${encodeURIComponent(q[k])}`).join('&')
  route.fullPath = qs ? `${path}?${qs}` : path
}

// ---- web 路径 → uni 页面路径 ----
// ⚠️ **新增页面必须在这里登记一行**，否则 `toUniUrl()` 会走下面的兜底分支悄悄跳回首页
// （2026-10-06 实测：漏登记 `/admin/schedule` → 点「定时任务」跳到了首页，且控制台无任何报错）。
const STATIC: Record<string, string> = {
  '/': 'pages/index/index',
  '/search': 'pages/search/index',
  '/latest': 'pages/latest/index',
  '/rank': 'pages/rank/index',
  '/me': 'pages/me/index',
  '/messages': 'pages/messages/index',
  '/login': 'pages/login/index',
  '/admin': 'pages/admin/index',
  '/admin/logs': 'pages/admin/logs',
  '/admin/users': 'pages/admin/users',
  '/admin/schedule': 'pages/admin/schedule',
  '/admin/comics': 'pages/admin/comics',
}

function withQuery(page: string, query: Record<string, unknown>): string {
  const qs = Object.keys(query)
    .filter((k) => query[k] !== undefined && query[k] !== null && query[k] !== '')
    .map((k) => `${k}=${encodeURIComponent(String(query[k]))}`)
    .join('&')
  return qs ? `${page}?${qs}` : page
}

/** 把 web 路由（`/comic/3`、`{path:'/search',query:{keyword:'x'}}`）解析为 uni 页面地址 */
export function toUniUrl(to: NavTarget): string {
  // ⚠️ `{ query }`（**只给 query、不给 path**）是 vue-router 的写法，语义是「在**当前路径**上改查询」——
  // 分类页的筛选/搜索就是这么调的（`router.replace({ query: {...} })`）。缺省 path 即取当前路由的
  // path；少了这个兜底，path 是 undefined，下面 `path.indexOf('?')` 直接抛 TypeError，
  // 调用方那句 `load()` 再也执行不到 → 点标签只动高亮、不查数据（2026-09-22 修）。
  let path = typeof to === 'string' ? to : (to.path || route.path)
  const query: Record<string, unknown> = typeof to === 'string' ? {} : { ...(to.query ?? {}) }

  const qi = path.indexOf('?')
  if (qi >= 0) {
    for (const kv of path.slice(qi + 1).split('&')) {
      if (!kv) continue
      const [k, v = ''] = kv.split('=')
      query[decodeURIComponent(k)] = decodeURIComponent(v)
    }
    path = path.slice(0, qi)
  }

  if (STATIC[path]) return withQuery(STATIC[path], query)

  const m1 = path.match(/^\/comic\/(\d+)$/)
  if (m1) return withQuery('pages/comic/index', { id: m1[1], ...query })

  const m2 = path.match(/^\/reader\/(\d+)\/(\d+)$/)
  if (m2) return withQuery('pages/reader/index', { comicId: m2[1], chapterId: m2[2], ...query })

  // 兜底：未登记的路径静默跳首页是踩过的坑（漏登记 `/admin/schedule` → 点入口跳到首页、
  // 控制台一点提示都没有）。这里主动出声，让「忘了登记 STATIC」当场可见。
  console.warn(`[router] 未登记的 web 路径 ${path} → 兜底回首页；请在 utils/router.ts 的 STATIC 里登记`)
  return withQuery('pages/index/index', {})
}

function currentPagePath(): string {
  const pages = getCurrentPages()
  const cur = pages.length ? pages[pages.length - 1] : null
  return cur ? `/${cur.route}` : ''
}

function go(to: NavTarget, replace: boolean): void {
  const url = `/${toUniUrl(to)}`
  const target = url.split('?')[0]

  // uni 不允许 navigateTo 到当前页 → 同页变更走「本地状态 + H5 地址栏同步」
  if (target === currentPagePath()) {
    if (typeof to !== 'string') setRoute(route.path, to.query ?? {})
    // #ifdef H5
    history.replaceState(null, '', `#${url}`)
    // #endif
    return
  }

  if (replace) {
    uni.redirectTo({ url, fail: () => uni.navigateTo({ url }) })
  } else {
    uni.navigateTo({ url, fail: () => uni.redirectTo({ url }) })
  }
}

// ---- 层级返回（「上一级」是**写死的树**，不是浏览历史）----
//
// 为什么不用 `uni.navigateBack` / `history.back()`：返回目标依赖**运行态**（页面栈 / 浏览器历史），
// H5 **一刷新这些就没了** —— 彼时返回要么无效、要么落到意料之外的页面（2026-10-09 用户报：
// 「一刷新页面返回的逻辑就失效」）。层级树不依赖任何运行态：每个二级页的**上级是确定的**，
// 刷新 / 直接打开链接（如 `#/comic/44`）/ 新标签页打开都成立。
//
// ⚠️ 新增二级页要在这里登记上级 —— 它与 STATIC 是**两件事**：STATIC 管「怎么去」（去程映射），
//    这里管「怎么回」（回程层级）。

/** 静态二级页的固定上级：都回首页；管理台子页回「采集管理」（与顶部选项卡栏的语义一致）。 */
const PARENTS: Record<string, string> = {
  '/rank': '/',
  '/me': '/',
  '/messages': '/',
  '/login': '/',
  '/admin': '/',
  '/admin/logs': '/admin',
  '/admin/users': '/admin',
  '/admin/schedule': '/admin',
  '/admin/comics': '/admin',
}

/** 当前路径的**固定上级**（层级返回的目标；不依赖页面栈 / 浏览历史）。 */
export function parentOf(path: string): string {
  // 带参数的两类页面：上级能从路径本身推出来
  const reader = path.match(/^\/reader\/(\d+)(?:\/|$)/)
  if (reader) return `/comic/${reader[1]}`             // 阅读器 → 它那一部的详情页
  if (/^\/comic\/\d+$/.test(path)) return '/latest'    // 详情 → 最近更新页（2026-10-09 用户指定）
  return PARENTS[path] || '/'
}

/** 同 vue-router 的 router 实例（仅保留项目实际用到的三个方法） */
export function useRouter() {
  return {
    push: (to: NavTarget) => go(to, false),
    replace: (to: NavTarget) => go(to, true),
    // 「返回上一层」= 跳**固定上级**（`parentOf`）并**替换当前页**：不依赖浏览历史，
    // 刷新后同样有效；替换而非压栈 —— 来回多次也不会把页面栈越叠越深。
    back: () => go(parentOf(route.path), true),
  }
}

/**
 * 「新标签页打开」：H5 用 window.open 开新标签（详情页/书架的「续读」语义）；
 * 小程序 / App 没有新标签页概念 → 退化为同页跳转，保证功能可用。
 */
export function openNewTab(to: string): void {
  const url = `/${toUniUrl(to)}`
  // #ifdef H5
  window.open(`${location.origin}${location.pathname}#${url}`, '_blank')
  // #endif
  // #ifndef H5
  uni.navigateTo({ url })
  // #endif
}
