// 全局事件总线 —— 基于 window 的自定义事件（CustomEvent）。
//
// 用途：api 层（auth.ts）广播登录态变更，Pinia store 监听后重读 → 全站同步。
// 事件名即字符串（如 `'auth:changed'`）；本层只做薄封装，保持 emit / on / off 三件套。

type Handler = (...args: unknown[]) => void

export function emit(name: string, ...args: unknown[]): void {
  window.dispatchEvent(new CustomEvent(name, { detail: args }))
}

export function on(name: string, handler: Handler): void {
  window.addEventListener(name, handler as EventListener)
}

export function off(name: string, handler?: Handler): void {
  if (handler) window.removeEventListener(name, handler as EventListener)
}
