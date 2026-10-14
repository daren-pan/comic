// 弹窗兼容层 —— 全站唯一的弹窗出口（只有 L0 碰平台 API）。
//
// 统一走 uni 的 `uni.showModal`（渲染 uni 自己的弹窗组件，样式与交互全站一致）；
// 页面里**不再直接写 `window.alert` / `window.confirm`**（ESLint 已禁，见 eslint.config.mjs）。
//
// 为什么还要包一层，而不是调用点直接写 uni.showModal：
//   1. 调用点只关心「提示一句」/「确认还是取消」，直接写要铺 4 行回调；
//   2. uni 的 Promise 化返回形态在版本间有过差异（`res` 与 `[err, res]` 两种），
//      这里统一用**回调式**包成自己的 Promise，行为可预期、不随版本变。

/** 提示弹窗（只有一个「知道了」）。失败也 resolve —— 弹窗失败不该打断业务流程。 */
export function showAlert(content: string, title = '提示'): Promise<void> {
  return new Promise((resolve) => {
    uni.showModal({
      title,
      content,
      showCancel: false,
      success: () => resolve(),
      fail: () => resolve(),
    })
  })
}

/** 确认弹窗 → `true` = 确定，`false` = 取消（或弹窗不可用时保守当取消） */
export function showConfirm(content: string, title = '请确认'): Promise<boolean> {
  return new Promise((resolve) => {
    uni.showModal({
      title,
      content,
      success: (r) => resolve(!!r.confirm),
      fail: () => resolve(false),
    })
  })
}
