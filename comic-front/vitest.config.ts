// vitest 配置 —— **刻意独立于 `vite.config.ts`**。
//
// 为什么不用后者：那份配置里挂了 `@dcloudio/vite-plugin-uni`，它会去处理
// pages.json / manifest.json、注入 uni 运行时 —— 单测只测**纯函数**
// （路由映射、季节判断），不需要这些，加载插件只会引入无关失败。
//
// 测什么、为什么测那几个（见 tests/ 下的注释）：
//   - `utils/router.ts` 的 `toUniUrl` / `parentOf`：两张手写映射表最容易漏改，
//     而漏改的后果是**静默跳回首页**（有 `console.warn` 但没人看）
//   - `utils/season.ts` 的 `getSeason`：季节边界（2/3 月、5/6 月…）容易写错
import { defineConfig } from 'vitest/config'

export default defineConfig({
  test: {
    include: ['tests/**/*.test.ts'],
    environment: 'node',
  },
})
