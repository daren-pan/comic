<script setup lang="ts">
// 应用根组件（纯 Web）：只挂路由出口。
//
// 全站布局（顶栏 / 底栏 / 抽屉 / 消息 toast）由各页面用 `<Layout>` 自行包裹 —— 与 comic-front
// 的结构保持一致（原 uni 版因「页面级渲染」这么做，纯 Web 版沿用同一结构，页面代码因此零改动迁移）。
//
// 应用级副作用（主题 / 布局模式往 <html> 挂类、userStore 事件监听、消息轮询）分别在
// utils/theme.ts、utils/layout.ts 的模块顶层与 components/Layout.vue 里触发，本组件不承担。
</script>

<template>
  <RouterView />
</template>
