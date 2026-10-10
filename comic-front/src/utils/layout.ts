// 页面布局模式（移动版 / 网页版）—— 全站唯一来源。
//
// 只做三件事：**存**上一次的选择、**算**当前模式、**把模式类挂到根节点**。
// 布局本身全在 CSS：移动端是基准（各页 <style> 的主体），网页版写在 `.mode-web`
// 前缀下做**增量覆盖**（见 style.css 与各页 <style> 末尾的「网页版」段）——
// 这里不碰任何具体样式。
//
// 默认值（未存过时）**按 UA 判定**（2026-10-10 用户定）：浏览器访问时根据请求里的
// 手机端 / 电脑端标识选择 —— 手机 → 移动版，电脑 → 网页版；小程序 / App 恒为移动版
// （本端没有网页形态）。手动切换后以用户选择为准（存本地，跨会话保留）。
//
// 挂载点与主题一致（utils/theme.ts）：H5 的 `<html>` —— `.mode-web` 挂上去后
// 整棵子树的 CSS（含各页 scoped 样式）都能匹配到它。小程序没有可动态加类的根节点，
// 也不会有网页模式，apply() 在那边是空操作。

import { computed, ref } from 'vue'
import { storage } from './storage'

export type LayoutMode = 'mobile' | 'web'

const KEY = 'comic_layout_mode'

/** 手机端 UA 特征（取常见集合；电脑端一个都不命中）。
 *  ⚠️ iPadOS 13+ 的 Safari 报的是 Macintosh UA（桌面特征）→ 归网页版，属预期。 */
const MOBILE_UA = /Android|iPhone|iPad|iPod|Mobile|HarmonyOS|Windows Phone|BlackBerry|Opera Mini|IEMobile/i

function uaIsMobile(): boolean {
  let mobile = true // 非 H5（小程序 / App）恒为移动版
  // #ifdef H5
  mobile = MOBILE_UA.test(navigator.userAgent)
  // #endif
  return mobile
}

function initial(): LayoutMode {
  const saved = storage.get(KEY)
  if (saved === 'mobile' || saved === 'web') return saved
  return uaIsMobile() ? 'mobile' : 'web'
}

const mode = ref<LayoutMode>(initial())

function apply(m: LayoutMode): void {
  // #ifdef H5
  document.documentElement.classList.toggle('mode-web', m === 'web')
  // #endif
}

apply(mode.value) // 首屏就定下来（同主题：避免先按移动版渲染、再闪成网页版）

export function useLayoutMode() {
  return {
    mode,
    isWebMode: computed(() => mode.value === 'web'),
    setMode,
    toggleMode,
  }
}

export function setMode(m: LayoutMode): void {
  if (mode.value === m) return
  mode.value = m
  storage.set(KEY, m)
  apply(m)
}

export function toggleMode(): void {
  setMode(mode.value === 'web' ? 'mobile' : 'web')
}
