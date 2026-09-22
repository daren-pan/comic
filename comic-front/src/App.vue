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

<style>
/* 小程序端的 `button` 默认样式归一化（H5 端的对应项在 uni-compat.css，选择器是 html uni-button）。
 *
 * H5 上 uni 把 button 编译成 uni-button 包装元素，②③ 修的是它；而**小程序端 button 就是原生组件**，
 * 自带灰底、固定行高，还有一圈由 after 伪元素画出来的边框 —— comic-web 的样式表是按「浏览器原生
 * button」写的，不归一会让 60 个按钮全都多出方框、底色也不对（纯文字按钮尤其明显）。
 * 取值与 uni-compat.css 的 H5 版本保持一致，两端视觉同源；业务 CSS 的 .btn / .msg-btn 权重更高。
 *
 * 为什么放在 App.vue 而不是 uni-compat.css：条件编译**只在 uni 会预处理的文件里生效**
 * （.vue 的 style 算，独立 .css 文件不算）。写在 .css 里时那对平台标记只是普通注释、会被压缩器
 * 去掉，规则于是**两端都生效**：H5 下 uni-button 内部还有一个原生 button，会同时命中内外两层，
 * padding 叠成双份、按钮变宽，正好破坏 uni-compat.css 为对齐原生度量做的归一化（已实测确认）。
 *
 * 只写 MP-WEIXIN：本项目当前只构建微信小程序，接其他小程序平台需补对应平台宏。 */
/* #ifdef MP-WEIXIN */
button {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  margin: 0;
  padding: 1px 6px;
  font-size: 13.3333px;
  line-height: normal;
  background: transparent;
  border: none;
  overflow: visible;
}
button::after { border: none; }
/* #endif */
</style>
