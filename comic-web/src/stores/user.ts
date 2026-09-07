// 登录态全局 store（Pinia）
//
// 设计（方案一 · 事件解耦）：
// - token/user 的「持久化真相」仍在 api 层 localStorage（setAuth/clearAuth 管理，刷新不丢）；
// - 本 store 是它的「响应式内存镜像」，供全站组件实时读取（顶栏/收藏/个人中心等）；
// - 同步机制：api 层在 setAuth/clearAuth 时派发 window 自定义事件 'auth:changed'，
//   本 store 在 init() 里监听该事件 → 从 localStorage 重新读入 → 全站组件自动更新。
//   这样 api 层不 import store、store 才 import api，避免循环依赖。
import { defineStore } from 'pinia'
import { computed, ref } from 'vue'
import {
  clearAuth,
  currentUser,
  getToken,
  login as apiLogin,
  register as apiRegister,
  setAuth,
} from '../api'
import type { User } from '../types'

const AUTH_EVENT = 'auth:changed'

export const useUserStore = defineStore('user', () => {
  // 初始态：从 localStorage 读（刷新页面后登录态仍在）
  const token = ref<string | null>(getToken())
  const user = ref<User | null>(currentUser())

  const isLoggedIn = computed(() => !!token.value)

  // 从 localStorage 重读（事件触发后调用）
  function sync() {
    token.value = getToken()
    user.value = currentUser()
  }

  // 启动时监听 api 层的登录态变更事件（只注册一次）
  let bound = false
  function init() {
    if (bound) return
    window.addEventListener(AUTH_EVENT, sync)
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

  return { token, user, isLoggedIn, init, sync, login, register, logout }
})
