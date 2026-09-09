// API 服务层入口 —— 按职责拆分子模块后统一导出
//  ├─ request.ts    HTTP 请求层（axios 实例 + 拦截器 + request<T> 剥壳）
//  ├─ auth.ts       登录态与匿名身份（localStorage 持久化 + auth:changed 事件广播）
//  ├─ content.ts    内容接口（漫画/章节/分页/分类）
//  └─ user.ts       用户中心接口（认证/收藏/历史）
//
// 组件统一 `import { ... } from '../api'`，对外签名与旧单文件版完全一致。

export * from './auth'
export * from './request'
export * from './content'
export * from './user'
export * from './admin'
