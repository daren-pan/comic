import { defineConfig } from 'vite'
import uni from '@dcloudio/vite-plugin-uni'

// 开发模式：H5 端由 Vite 提供，/api 代理到真实后端（api-service，:8000）
// 与 comic-web 的代理配置保持一致（约定不变）。
//
// ⚠️ 端口用 5174（**不是** comic-web 的 5173）：两者若都监听 5173，一个绑 127.0.0.1、
// 一个绑 0.0.0.0，浏览器访问 127.0.0.1:5173 会被 comic-web 抢走（静默开错应用）。
// 分开端口后两个前端可同时运行、互不干扰。
export default defineConfig({
  plugins: [uni()],
  server: {
    port: 5174,
    host: true,
    // ⚠️ 必须忽略「原子写」的临时目录，否则 dev server 会被写文件动作直接打挂（2026-10-06 实测）：
    // AI 协作工具（如 DSH）保存文件时按「同级 .<文件名>.<pid>.<uuid>.tmpdir/ 里写 .tmp，再改名」的
    // 原子写落盘，chokidar 会去 watch 那个**正被写者锁住**的临时文件并抛
    //   Error: EBUSY: resource busy or locked, watch '...\.x.vue.<pid>.<uuid>.tmpdir\x.vue.tmp'
    // 这是 watch 层未捕获错误 → node 进程直接退出（dev server 挂掉，页面变不可达）。
    // 忽略这类目录即可；临时目录本身写完就被删，不影响热更新。
    watch: {
      ignored: ['**/*.tmpdir/**'],
    },
    proxy: {
      '/api': { target: 'http://127.0.0.1:8000', changeOrigin: true },
    },
  },
})
