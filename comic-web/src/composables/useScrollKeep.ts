// 列表页 keep-alive 的滚动位置保持 —— 从详情页返回时停在原处（对齐 comic-front 的 uni 页面栈行为）。
//
// ⚠️ 为什么不用 vue-router 的 scrollBehavior(savedPosition)（2026-10-15 探针实测）：
//   SPA 内部导航下 vue-router 记录的 `history.state.scroll` 是「**到达**该条目时」的位置
//   （通常是 0），不是「离开时」的 —— 返回时 savedPosition 读到的是 {top:0}，恢复不了。
//   所以自己记录：滚动时持续记下位置，deactivated 后保留，activated 时（DOM 已恢复）滚回去。
//
// 用法（列表页 setup 里一行）：
//     useScrollKeep()
import { nextTick, onActivated, onBeforeUnmount, onDeactivated, onMounted } from 'vue'

export function useScrollKeep(): void {
  let lastY = 0
  let active = true // 只在激活状态记录 —— 否则缓存页会在「别的页面滚动」时被污染

  const onScroll = () => {
    if (active) lastY = window.scrollY
  }

  onMounted(() => window.addEventListener('scroll', onScroll, { passive: true }))
  onBeforeUnmount(() => window.removeEventListener('scroll', onScroll))

  onDeactivated(() => (active = false))
  onActivated(() => {
    active = true
    const y = lastY
    // 等一帧再滚：keep-alive 的 DOM 是同步恢复的，但网格布局与吸顶组头可能还要一拍。
    // （卡片封面是固定比例盒，页面高度不依赖图片加载，正常一帧即够。）
    nextTick(() => requestAnimationFrame(() => window.scrollTo(0, y)))
  })
}
