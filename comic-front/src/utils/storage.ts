// 存储适配层 —— 把 comic-web 里散落的 `localStorage.*` 调用统一收敛到这里。
//
// 底层换成 uni 的跨端存储 API：H5 落到 localStorage，小程序/App 落到各自原生存储。
// **语义与 localStorage 保持一致**（字符串存取、读不到返回 null），
// 这样 api/stores 里的读写逻辑一行都不用改。

export const storage = {
  /** 读（无值返回 null，与 localStorage.getItem 一致） */
  get(key: string): string | null {
    try {
      const v = uni.getStorageSync(key)
      return v === '' || v === undefined || v === null ? null : String(v)
    } catch {
      return null
    }
  },

  /** 写（失败静默：存储配额/隐私模式不该打断主流程） */
  set(key: string, value: string): void {
    try {
      uni.setStorageSync(key, value)
    } catch {
      /* ignore */
    }
  },

  /** 删 */
  remove(key: string): void {
    try {
      uni.removeStorageSync(key)
    } catch {
      /* ignore */
    }
  },
}
