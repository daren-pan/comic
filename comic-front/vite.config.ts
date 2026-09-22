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
    proxy: {
      '/api': { target: 'http://127.0.0.1:8000', changeOrigin: true },
    },
  },
})
