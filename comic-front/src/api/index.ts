// API 服务层入口 —— 按职责拆分子模块后统一导出
//  ├─ request.ts    HTTP 请求层（uni.request 单通道 + request<T> 剥壳）
//  ├─ auth.ts       登录态与匿名身份（本地存储持久化 + auth:changed 事件广播）
//  ├─ content.ts    内容接口（漫画/章节/分页/分类）
//  ├─ user.ts       用户中心接口（认证/收藏/历史）
//  ├─ admin.ts      管理台接口（采集/巡检/任务）
//  └─ ondemand.ts   源站搜索与按需导入（搜索页「其他来源」）
//
// 组件统一 `import { ... } from '../api'`，对外签名与 comic-web 完全一致。

export * from './auth'
export * from './request'
export * from './content'
export * from './user'
export * from './admin'
export * from './ondemand'
