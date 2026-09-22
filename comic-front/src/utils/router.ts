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

export type NavTarget = string | { path: string; query?: Record<string, unknown> }

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
const STATIC: Record<string, string> = {
  '/': 'pages/index/index',
  '/search': 'pages/search/index',
  '/latest': 'pages/latest/index',
  '/rank': 'pages/rank/index',
  '/me': 'pages/me/index',
  '/login': 'pages/login/index',
  '/admin': 'pages/admin/index',
  '/admin/logs': 'pages/admin/logs',
  '/admin/users': 'pages/admin/users',
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
  let path = typeof to === 'string' ? to : to.path
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

/** 同 vue-router 的 router 实例（仅保留项目实际用到的三个方法） */
export function useRouter() {
  return {
    push: (to: NavTarget) => go(to, false),
    replace: (to: NavTarget) => go(to, true),
    back: () => uni.navigateBack({ delta: 1, fail: () => uni.redirectTo({ url: '/pages/index/index' }) }),
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
