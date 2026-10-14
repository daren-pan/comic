// 登录态全局 store（Pinia）
//
// 设计（方案一 · 事件解耦）：
// - token/user 的「持久化真相」仍在 api 层本地存储（setAuth/clearAuth 管理，刷新不丢）；
// - 本 store 是它的「响应式内存镜像」，供全站组件实时读取（顶栏/收藏/个人中心等）；
// - 同步机制：api 层在 setAuth/clearAuth 时广播 'auth:changed'（uni.$emit），
//   本 store 在 init() 里监听该事件 → 从本地存储重新读入 → 全站组件自动更新。
//   这样 api 层不 import store、store 才 import api，避免循环依赖。
import { defineStore } from 'pinia'
import { computed, ref } from 'vue'
import {
  clearAuth,
  currentUser,
  getToken,
  login as apiLogin,
  me as apiMe,
  register as apiRegister,
  setAuth,
  setUser,
} from '../api'
import type { User } from '../types'
import { on } from '../utils/event'

const AUTH_EVENT = 'auth:changed'

export const useUserStore = defineStore('user', () => {
  // 初始态：从本地存储读（刷新页面后登录态仍在）
  const token = ref<string | null>(getToken())
  const user = ref<User | null>(currentUser())

  const isLoggedIn = computed(() => !!token.value)

  // 角色三档（见 docs/auth.md §8）：
  //   superadmin 超级管理员 —— 管理台 + 日志 + **授权页**（全库唯一，只有首个注册用户）
  //   admin      普通管理员 —— 管理台 + 日志，**进不了授权页**
  //   user       普通用户（默认）—— 无管理台权限
  // 这两个判断只是体验层（顶栏入口与路由守卫）；真正的门在后端 require_admin /
  // require_superadmin，改 localStorage 骗不过去。
  // 旧 token 里 localStorage 可能没有 role（本次改动前登录的），守卫会先刷新一次。
  const isAdmin = computed(() => user.value?.role === 'admin' || user.value?.role === 'superadmin')
  const isSuperAdmin = computed(() => user.value?.role === 'superadmin')

  // 从本地存储重读（事件触发后调用）
  function sync() {
    token.value = getToken()
    user.value = currentUser()
  }

  // 启动时监听 api 层的登录态变更事件（只注册一次）
  let bound = false
  function init() {
    if (bound) return
    on(AUTH_EVENT, sync)
    bound = true
    sync() // 初次进入同步一次（如 httpAuth 401 清除发生在 store 创建前）
  }

  async function login(username: string, password: string) {
    const res = await apiLogin(username, password)
    // setAuth 写 localStorage + 广播 'auth:changed' → sync 由事件触发
    setAuth(res)
    return res
  }

  async function register(username: string, password: string, nickname = '') {
    const res = await apiRegister(username, password, nickname)
    setAuth(res)
    return res
  }

  function logout() {
    clearAuth() // 清 localStorage + 派发事件 → sync 由事件触发
  }

  /**
   * 拉一次 `/api/auth/me` 并回写本地用户（token 不变）。返回最新 user。
   * 用途：路由守卫进管理台前确认角色 —— 角色是**每次请求从库里读**的，
   * 本地缓存的 role 可能已过期（被授权 / 被取消授权）。
   */
  async function refresh() {
    const fresh = await apiMe()
    setUser(fresh) // 写 localStorage + 广播 → sync 由事件触发
    return fresh
  }

  return {
    token,
    user,
    isLoggedIn,
    isAdmin,
    isSuperAdmin,
    init,
    sync,
    login,
    register,
    logout,
    refresh,
  }
})
