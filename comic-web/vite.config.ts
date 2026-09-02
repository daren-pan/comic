import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'

// base 用相对路径，构建产物可直接双击 index.html 或挂任意静态服务器
export default defineConfig({
  base: './',
  plugins: [vue()],
  server: {
    port: 5173,
    host: true,
    // 架构方案：开发模式代理到真实后端（api-service）
    proxy: {
      '/api': { target: 'http://127.0.0.1:8000', changeOrigin: true },
    },
  },
})
