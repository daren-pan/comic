// vitest 配置 —— 独立于 `vite.config.ts`（那份挂了 vue 插件与 dev 代理；
// 单测只测**纯函数**，不需要这些）。
//
// 测什么、为什么测那几个（见 tests/ 下的注释）：
//   - `utils/nav.ts` 的 `parentOf`：手写映射表最容易漏改，漏改的后果是**静默跳回首页**
//   - `utils/season.ts` 的 `getSeason`：季节边界（2/3 月、5/6 月…）容易写错
//   - `composables/usePagedList`：翻页替换 vs 触底追加的语义、失败回退
import { defineConfig } from 'vitest/config'

export default defineConfig({
  test: {
    include: ['tests/**/*.test.ts'],
    environment: 'node',
  },
})
