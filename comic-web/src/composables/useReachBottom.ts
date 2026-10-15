// 触底加载触发 —— 替代 uni 的页面级生命周期 `onReachBottom`。
//
// 语义与 uni 版一致：「滚到接近底部」触发一次（不是「进视口」），由回调自己防重入
// （`usePagedList` 的 `loadMore` 内置「加载中不重入 / 已拉完不再请求」）。
//
// ⚠️ 为什么用 rAF 合并、而不是「200ms 时间节流」（2026-10-14 实测踩坑）：
//   原先按前缘节流检查位置 —— 用户滑到底**停手**时，最后一批 scroll 事件恰好落在
//   节流窗口里被丢弃，触底检查就不会执行；而此时已到最大滚动位置、**不会再产生任何
//   scroll 事件**，页面卡死在底部（必须上滚再下滚才恢复）—— 表现为「到底了显示
//   '继续下滑加载更多'，但要重新下拉一次才加载」（front 的 uni onReachBottom 是逐事件
//   检查，没有这个问题）。
//   rAF 合并：滚动事件只负责「预约一帧后的检查」，检查**永远执行到最后一帧** ——
//   停手时的最后位置一定会被检查；连续滚动时合并到帧率，行为与 uni 等价。
//
// 用法（与 comic-front 的 `onReachBottom(loadMore)` 一一对应）：
//     useReachBottom(loadMore)
import { onActivated, onBeforeUnmount, onDeactivated, onMounted } from 'vue'

export function useReachBottom(onReach: () => void, threshold = 300): void {
  let scheduled = false
  let disposed = false
  let active = true // keep-alive 激活状态（见下）

  const check = () => {
    scheduled = false
    if (disposed || !active) return
    const el = document.documentElement
    if (el.scrollHeight - el.scrollTop - el.clientHeight < threshold) onReach()
  }
  const handler = () => {
    if (scheduled) return // 一帧内只检查一次（事件很密，位置检查合并到帧率）
    scheduled = true
    requestAnimationFrame(check)
  }

  onMounted(() => window.addEventListener('scroll', handler, { passive: true }))
  onBeforeUnmount(() => {
    disposed = true // 卸载后若还有未执行的 rAF，检查直接跳过
    window.removeEventListener('scroll', handler)
  })

  // keep-alive（2026-10-15）：页面被缓存切走（如进详情）时暂停检查 —— 否则在详情页滚动到底
  // 会误触发本页的「触底加载」，后台凭空多拉一批（返回时列表比离开时多出一截）。
  onDeactivated(() => (active = false))
  onActivated(() => (active = true))
}
