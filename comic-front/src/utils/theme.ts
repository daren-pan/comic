// 主题（明亮 / 夜间）—— 全站唯一来源。
//
// 只做三件事：**存**上一次的选择、**算**当前主题、**把主题类挂到根节点**。
// 颜色本身全在 style.css 的 `.theme-dark` 变量组里，这里不碰任何具体色值。
//
// 挂载点有两处，缺一不可：
//   1) Layout.vue 的 `.app-shell`（模板根）—— 三端都生效，靠 CSS 变量继承覆盖整棵子树；
//   2) H5 的 `<html>` —— 让 `html/body/page` 自身的背景色也跟着切（`.app-shell` 之外还有
//      滚动到尽头时露出来的区域）。小程序没有可动态加类的根节点，那部分由 `.app-shell`
//      的 `min-height: 100vh` 兜住。
//
// 未存过时**跟随系统**：H5 用 `prefers-color-scheme`，小程序/App 用 `uni.getSystemInfoSync().theme`。

import { computed, ref } from 'vue'
import { storage } from './storage'

export type Theme = 'light' | 'dark'

const KEY = 'comic_theme'

function systemPrefersDark(): boolean {
  let dark = false
  // #ifdef H5
  dark = !!(window.matchMedia && window.matchMedia('(prefers-color-scheme: dark)').matches)
  // #endif
  // #ifndef H5
  try {
    dark = uni.getSystemInfoSync?.()?.theme === 'dark'
  } catch {
    dark = false
  }
  // #endif
  return dark
}

function initial(): Theme {
  const saved = storage.get(KEY)
  if (saved === 'light' || saved === 'dark') return saved
  return systemPrefersDark() ? 'dark' : 'light'
}

const theme = ref<Theme>(initial())

function apply(t: Theme): void {
  // #ifdef H5
  document.documentElement.classList.toggle('theme-dark', t === 'dark')
  // #endif
}

apply(theme.value) // 首屏就定下来，避免先亮后暗闪一下

export function useTheme() {
  return {
    theme,
    isDark: computed(() => theme.value === 'dark'),
    setTheme,
    toggleTheme,
  }
}

export function setTheme(t: Theme): void {
  if (theme.value === t) return
  theme.value = t
  storage.set(KEY, t)
  apply(t)
}

export function toggleTheme(): void {
  setTheme(theme.value === 'dark' ? 'light' : 'dark')
}
