import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'

// 后端（FastAPI）跑在 8899，界面跑在 5175；`/api` 由 vite 代理过去，
// 前端代码里直接写 fetch('/api/...') 即可，不用关心端口。
export default defineConfig({
  plugins: [vue()],
  server: {
    host: '127.0.0.1',
    port: 5175,
    strictPort: true,
    open: false,
    // 有些编辑器/工具用「临时文件 + rename」写盘，Windows 上目录监视会撞 EBUSY
    // 直接把 vite 进程搞崩。这些临时产物与源码无关，忽略掉。
    watch: {
      ignored: ['**/.*.tmpdir/**', '**/.*.tmp', '**/node_modules/**', '**/dist/**'],
    },
    proxy: {
      '/api': {
        target: 'http://127.0.0.1:8899',
        changeOrigin: true,
      },
    },
  },
})
