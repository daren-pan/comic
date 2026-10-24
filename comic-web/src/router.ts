import { createRouter, createWebHashHistory } from 'vue-router'
import type { RouteLocationNormalized } from 'vue-router'
import { isLoggedIn } from './api'
import { useMessageStore } from './stores/message'
import { useUserStore } from './stores/user'

/**
 * 管理台 / 日志 / 授权页的门卫。
 *
 * 三档角色（见 `docs/auth.md` §8）对应两种门禁：
 *
 * | 路由 | 门槛 | 谁能进 |
 * |---|---|---|
 * | `/#/admin`、`/#/admin/comics`、`/#/admin/schedule`、`/#/admin/logs` | `requireRole(false)` | 超级管理员 + **普通管理员** |
 * | `/#/admin/users`（授权页） | `requireRole(true)` | **仅超级管理员** |
 *
 * 授权页必须单独把门 —— 否则普通管理员反手就能把真正的超管降级（2026-09-18 实测到的漏洞）。
 *
 * 每道门三步，顺序固定：
 * 1. **未登录** → 跳登录页（带 `redirect`）；
 * 2. **向 `/api/auth/me` 复核角色** —— 角色是"每次请求从库里读"的，本机 localStorage 里的
 *    role 可能已过期（刚被授权 / 刚被取消授权，或本次改动前登录的旧缓存里根本没有 role）；
 * 3. **角色不够** → 回首页并在消息中心留一条提示。
 *
 * ⚠️ 这只是**体验层**的门：真正的门是后端的 `require_admin` / `require_superadmin`。
 */
function requireRole(superOnly: boolean) {
  return async (
    to: RouteLocationNormalized,
  ): Promise<true | { name: string; query?: Record<string, string> }> => {
    if (!isLoggedIn()) {
      return { name: 'login', query: { redirect: to.fullPath } }
    }
    const userStore = useUserStore()
    try {
      await userStore.refresh()
    } catch {
      // 401：请求层已清登录态并跳登录页，这里只需终止本次导航
      return { name: 'login', query: { redirect: to.fullPath } }
    }
    const ok = superOnly ? userStore.isSuperAdmin : userStore.isAdmin
    if (!ok) {
      useMessageStore().notify(
        superOnly ? '需要超级管理员权限' : '需要管理员权限',
        `${to.fullPath} ${
          superOnly ? '仅超级管理员可访问（授权只有超级管理员能做）' : '仅管理员可访问'
        }`,
      )
      return { name: 'home' }
    }
    return true
  }
}

/** keep-alive 缓存的列表页（路由名）—— 与 App.vue 的 keepAliveViews（组件名）一一对应 */
const KEEP_ALIVE_ROUTES = new Set(['home', 'latest', 'rank', 'search'])

export const router = createRouter({
  // hash 模式：构建产物可离线双击打开，无需服务器配置
  history: createWebHashHistory(),
  routes: [
    { path: '/', name: 'home', component: () => import('./views/HomeView.vue') },
    { path: '/search', name: 'search', component: () => import('./views/SearchView.vue') },
    { path: '/latest', name: 'latest', component: () => import('./views/LatestView.vue') },
    { path: '/rank', name: 'rank', component: () => import('./views/RankingView.vue') },
    { path: '/comic/:id', name: 'detail', component: () => import('./views/ComicDetailView.vue') },
    { path: '/reader/:comicId/:chapterId', name: 'reader', component: () => import('./views/ReaderView.vue') },
    { path: '/me', name: 'me', component: () => import('./views/MeView.vue') },
    { path: '/profile', name: 'profile', component: () => import('./views/ProfileView.vue') },
    { path: '/messages', name: 'messages', component: () => import('./views/MessagesView.vue') },
    { path: '/login', name: 'login', component: () => import('./views/LoginView.vue') },
    // 忘记密码（邮箱验证码重置，2026-10-24）：**不加 any 守卫** —— 忘记密码的人正是未登录状态
    { path: '/reset', name: 'reset', component: () => import('./views/ResetPasswordView.vue') },
    // 管理台：超级管理员 + 普通管理员
    { path: '/admin', name: 'admin', component: () => import('./views/AdminView.vue'), beforeEnter: requireRole(false) },
    { path: '/admin/comics', name: 'adminComics', component: () => import('./views/AdminComicsView.vue'), beforeEnter: requireRole(false) },
    { path: '/admin/schedule', name: 'adminSchedule', component: () => import('./views/AdminScheduleView.vue'), beforeEnter: requireRole(false) },
    { path: '/admin/logs', name: 'logs', component: () => import('./views/LogsView.vue'), beforeEnter: requireRole(false) },
    // 授权页：**仅超级管理员**
    { path: '/admin/users', name: 'adminUsers', component: () => import('./views/AdminUsersView.vue'), beforeEnter: requireRole(true) },
    { path: '/:pathMatch(.*)*', redirect: '/' },
  ],
  scrollBehavior(_to, _from, savedPosition) {
    // popstate（后退/前进）且目标是列表页：这里**不滚动** —— vue-router 的 savedPosition 在
    // SPA 内部导航下记录的是「到达该条目时」的位置（实测为 {top:0}，不是离开时的），不可用；
    // 滚动恢复由列表页自己的 useScrollKeep 在 activated 时做（配合 App.vue 的 keep-alive）。
    if (savedPosition && KEEP_ALIVE_ROUTES.has(_to.name as string)) return false
    // 其余导航（点链接进入新页面 / 非列表页的返回）→ 回顶
    return { top: 0 }
  },
})
