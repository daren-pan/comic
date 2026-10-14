// 层级返回（「上一级」是**写死的树**，不是浏览历史）—— 由 comic-front 的 router 兼容层抽来。
//
// 为什么不用 `router.back()` / `history.back()`：返回目标依赖**运行态**（浏览历史），
// 直接打开链接（如 `#/comic/44`）/ 新标签页打开时历史是空的 —— 彼时返回要么无效、
// 要么落到意料之外的页面。层级树不依赖任何运行态：每个二级页的**上级是确定的**。
//
// ⚠️ 新增二级页要在这里登记上级。

/** 静态二级页的固定上级：都回首页；管理台子页回「采集管理」（与顶部选项卡栏的语义一致）。 */
const PARENTS: Record<string, string> = {
  '/rank': '/',
  '/me': '/',
  '/profile': '/',
  '/messages': '/',
  '/login': '/',
  '/admin': '/',
  '/admin/logs': '/admin',
  '/admin/users': '/admin',
  '/admin/schedule': '/admin',
  '/admin/comics': '/admin',
}

/** 当前路径的**固定上级**（层级返回的目标；不依赖浏览历史）。 */
export function parentOf(path: string): string {
  // 带参数的两类页面：上级能从路径本身推出来
  const reader = path.match(/^\/reader\/(\d+)(?:\/|$)/)
  if (reader) return `/comic/${reader[1]}` // 阅读器 → 它那一部的详情页
  if (/^\/comic\/\d+$/.test(path)) return '/latest' // 详情 → 最近更新页（2026-10-09 用户指定）
  return PARENTS[path] || '/'
}

/** 「新标签页打开」：用 window.open 开新标签（详情页/书架的「续读」语义）。 */
export function openNewTab(path: string): void {
  window.open(`${location.origin}${location.pathname}#${path}`, '_blank')
}
