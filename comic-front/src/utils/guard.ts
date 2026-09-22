// 管理台门卫 —— 移植 comic-web 的 vue-router `beforeEnter: requireRole(...)`。
//
// uni 的页面栈**没有路由守卫钩子**，所以把这段逻辑抽成普通函数，由三个管理台页面在
// `onLoad` 里 `await` 一次；返回 `false` 时页面停止加载（已自行跳走）。
//
// 语义与 comic-web 完全一致 —— 三步，顺序固定：
//   1. **未登录** → 跳登录页（带 `redirect`）；
//   2. **向 `/api/auth/me` 复核角色** —— 角色是「每次请求从库里读」的，本机存的 role 可能已过期
//      （刚被授权 / 刚被取消授权，或旧缓存里根本没有 role）；
//   3. **角色不够** → 回首页并在消息中心留一条提示。
//
// 三档角色（见 docs/auth.md §8）对应两道门：
//   `requireRole(false)` → 管理台 / 日志：超级管理员 + 普通管理员
//   `requireRole(true)`  → 授权页：**仅超级管理员**
// 授权页必须单独把门，否则普通管理员反手就能把真正的超管降级。
//
// ⚠️ 这只是**体验层**的门；真正的门是后端的 `require_admin` / `require_superadmin`。
import { isLoggedIn } from '../api'
import { useMessageStore } from '../stores/message'
import { useUserStore } from '../stores/user'
import { useRouter } from './router'

export async function requireRole(superOnly: boolean, fullPath: string): Promise<boolean> {
  const router = useRouter()

  if (!isLoggedIn()) {
    router.replace(`/login?redirect=${encodeURIComponent(fullPath)}`)
    return false
  }

  const userStore = useUserStore()
  try {
    await userStore.refresh()
  } catch {
    // 401：请求层已清登录态并跳登录页，这里只需终止本次进入
    router.replace(`/login?redirect=${encodeURIComponent(fullPath)}`)
    return false
  }

  const ok = superOnly ? userStore.isSuperAdmin : userStore.isAdmin
  if (!ok) {
    useMessageStore().addSystem(
      superOnly ? '需要超级管理员权限' : '需要管理员权限',
      `${fullPath} ${
        superOnly ? '仅超级管理员可访问（授权只有超级管理员能做）' : '仅管理员可访问'
      }`,
    )
    router.replace('/')
    return false
  }

  return true
}
