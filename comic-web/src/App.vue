<script setup lang="ts">
// 应用根组件（纯 Web）：只挂路由出口。
//
// 全站布局（顶栏 / 底栏 / 抽屉 / 消息 toast）由各页面用 `<Layout>` 自行包裹 —— 与 comic-front
// 的结构保持一致（原 uni 版因「页面级渲染」这么做，纯 Web 版沿用同一结构，页面代码因此零改动迁移）。
//
// 应用级副作用（主题 / 布局模式往 <html> 挂类、userStore 事件监听、消息轮询）分别在
// utils/theme.ts、utils/layout.ts 的模块顶层与 components/Layout.vue 里触发，本组件不承担。
//
// **keep-alive（2026-10-15）**：列表类页面（首页 / 最近更新 / 热度排行 / 分类搜索）进详情页再
// 返回时，保留已加载的列表与滚动位置（对齐 comic-front 的 uni 页面栈行为）。不缓存的话返回会
// 重新挂载组件：列表重置回第一批（实测 54 张 → 18 张）、滚动归零、重发第 1 页请求。
// 其余页面（详情 / 阅读器 / 我的 / 登录 / 管理台）每次进入都该取新数据，不进缓存。
// ⚠️ 列表里的名字 = SFC 文件名（`<script setup>` 编译时注入的 `__name`），不是 router.ts 里的路由名。
// 配套改动：router.ts 的 scrollBehavior 恢复 savedPosition；useReachBottom / HomeView 的轮播
// 在 deactivated 时暂停（缓存后「离开页面」不再触发卸载）。
const keepAliveViews = ['HomeView', 'LatestView', 'RankingView', 'SearchView']
</script>

<template>
  <RouterView v-slot="{ Component }">
    <keep-alive :include="keepAliveViews">
      <component :is="Component" />
    </keep-alive>
  </RouterView>
</template>
