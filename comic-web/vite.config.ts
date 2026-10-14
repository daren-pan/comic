import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'

// base 用相对路径，构建产物可直接双击 index.html 或挂任意静态服务器
export default defineConfig({
  base: './',
  plugins: [vue()],
  server: {
    port: 5173,
    host: true,
    // ⚠️ 必须忽略「原子写」的临时目录，否则 dev server 会被写文件动作直接打挂（2026-10-06 实测）：
    // AI 协作工具保存文件时按「同级 .<文件名>.<pid>.<uuid>.tmpdir/ 里写 .tmp，再改名」的
    // 原子写落盘，chokidar 会去 watch 那个**正被写者锁住**的临时文件并抛 EBUSY → node 进程退出。
    watch: {
      ignored: ['**/*.tmpdir/**'],
    },
    // 开发模式代理到真实后端（api-service）
    proxy: {
      '/api': { target: 'http://127.0.0.1:8000', changeOrigin: true },
    },
  },
})
