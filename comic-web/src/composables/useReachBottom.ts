// 触底加载触发 —— 替代 uni 的页面级生命周期 `onReachBottom`。
//
// 语义与 uni 版一致：「滚到接近底部」触发一次（不是「进视口」），由回调自己防重入
// （`usePagedList` 的 `loadMore` 内置「加载中不重入 / 已拉完不再请求」）。
// 本层只做两件事：监听 window 滚动 + 200ms 节流（scroll 触发太密，避免无谓调用）。
//
// 用法（与 comic-front 的 `onReachBottom(loadMore)` 一一对应）：
//     useReachBottom(loadMore)
import { onBeforeUnmount, onMounted } from 'vue'

export function useReachBottom(onReach: () => void, threshold = 300): void {
  let last = 0
  const handler = () => {
    const now = Date.now()
    if (now - last < 200) return
    last = now
    const el = document.documentElement
    if (el.scrollHeight - el.scrollTop - el.clientHeight < threshold) onReach()
  }
  onMounted(() => window.addEventListener('scroll', handler, { passive: true }))
  onBeforeUnmount(() => window.removeEventListener('scroll', handler))
}
