// 存储适配层 —— 全站唯一的本地存储出口（不要绕过它直接用 localStorage，ESLint 已禁）。
//
// 语义与 localStorage 保持一致（字符串存取、读不到返回 null），
// 这样 api/stores 里的读写逻辑一行都不用改。

export const storage = {
  /** 读（无值返回 null，与 localStorage.getItem 一致） */
  get(key: string): string | null {
    try {
      return localStorage.getItem(key)
    } catch {
      return null
    }
  },

  /** 写（失败静默：存储配额 / 隐私模式不该打断主流程） */
  set(key: string, value: string): void {
    try {
      localStorage.setItem(key, value)
    } catch {
      /* ignore */
    }
  },

  /** 删 */
  remove(key: string): void {
    try {
      localStorage.removeItem(key)
    } catch {
      /* ignore */
    }
  },
}
