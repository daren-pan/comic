// 页面布局模式（移动版 / 网页版）—— 全站唯一来源。
//
// 只做两件事：**算**当前模式、**把模式类挂到根节点**。
// 布局本身全在 CSS：移动端是基准（各页 <style> 的主体），网页版写在 `.mode-web`
// 前缀下做**增量覆盖**（见 style.css 与各页 <style> 末尾的「网页版」段）——
// 这里不碰任何具体样式。
//
// 模式**只按 UA 判定**（2026-10-12 用户定，手动切换键已移除）：浏览器访问时根据
// 请求里的手机端 / 电脑端标识选择 —— 手机 → 移动版，电脑 → 网页版。不读写本地偏好，
// 每次访问按 UA 现判。
//
// 挂载点与主题一致（utils/theme.ts）：`<html>` —— `.mode-web` 挂上去后
// 整棵子树的 CSS（含各页 scoped 样式）都能匹配到它。

import { computed, ref } from 'vue'

export type LayoutMode = 'mobile' | 'web'

/** 手机端 UA 特征（取常见集合；电脑端一个都不命中）。
 *  ⚠️ iPadOS 13+ 的 Safari 报的是 Macintosh UA（桌面特征）→ 归网页版，属预期。 */
const MOBILE_UA = /Android|iPhone|iPad|iPod|Mobile|HarmonyOS|Windows Phone|BlackBerry|Opera Mini|IEMobile/i

function uaIsMobile(): boolean {
  return MOBILE_UA.test(navigator.userAgent)
}

const mode = ref<LayoutMode>(uaIsMobile() ? 'mobile' : 'web')

function apply(m: LayoutMode): void {
  document.documentElement.classList.toggle('mode-web', m === 'web')
}

apply(mode.value) // 首屏就定下来（同主题：避免先按移动版渲染、再闪成网页版）

export function useLayoutMode() {
  return {
    mode,
    isWebMode: computed(() => mode.value === 'web'),
  }
}
