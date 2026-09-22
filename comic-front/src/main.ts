import { createSSRApp } from 'vue'
import { createPinia } from 'pinia'
import App from './App.vue'
import './style.css'
// uni 内置组件（uni-button / uni-input / uni-form）的默认样式归一化 —— comic-front 专属，见文件内注释
import './uni-compat.css'

// uni-app 约定：导出 createApp 工厂（而非直接 mount）。
// 与 comic-web 的 main.ts 等价 —— 只是挂载方式换成 uni 运行时，Pinia 照旧全局注入，
// 全局样式同样在入口统一引入。
export function createApp() {
  const app = createSSRApp(App)
  app.use(createPinia())
  return { app }
}
