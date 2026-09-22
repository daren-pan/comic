<script setup lang="ts">
// uni-app 应用根组件。
//
// 与 comic-web 的 App.vue **不同**：uni-app 的 App.vue 是「应用级」容器，不参与页面渲染
// （各页面独立渲染），所以这里不放顶栏/页脚 —— 那部分被搬进了 components/Layout.vue，
// 由每个页面用 <Layout> 自行包裹。
//
// 这里只保留应用级生命周期钩子（后续接 App 冷启动、检查更新等逻辑用）。
import { onLaunch, onShow, onHide } from '@dcloudio/uni-app'

onLaunch(() => {
  // 应用启动（各端都会触发一次）
})

onShow(() => {
  // 应用进入前台
})

onHide(() => {
  // 应用进入后台
})
</script>

<template>
  <!-- uni-app 的 App.vue 不渲染模板，页面各自渲染 -->
</template>
