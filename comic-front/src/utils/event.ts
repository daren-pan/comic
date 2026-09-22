// 全局事件总线 —— 替代 comic-web 里的 `window.dispatchEvent(new CustomEvent(...))`。
//
// uni.$emit / uni.$on 在 H5 / 小程序 / App 都可用，语义与原来的自定义事件等价。
// 用途：api 层（auth.ts）广播登录态变更，Pinia store 监听后重读 → 全站同步。

type Handler = (...args: unknown[]) => void

export function emit(name: string, ...args: unknown[]): void {
  uni.$emit(name, ...args)
}

export function on(name: string, handler: Handler): void {
  uni.$on(name, handler)
}

export function off(name: string, handler?: Handler): void {
  uni.$off(name, handler)
}
