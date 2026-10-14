<script setup lang="ts">
// 三态视图：加载中 / 加载失败 / 暂无数据 —— 三者互斥，全站统一一处。
//
// ## 为什么要有它
//
// 这三态此前在各页模板里手写，文案共 **61 处、散在 12 个文件**，判断口径还不一致
// （有的用 `loading`、有的用 `ready`、有的直接看 `items.length === 0`）；改一句话
// 要翻十几个文件，样式也各写各的。
//
// ## 用法
//
//   <StateView :loading="loading && !ready" :error="error" :empty="!items.length">
//     <view class="grid">…</view>
//   </StateView>
//
// ⚠️ **`loading` 要传 `loading && !ready`**（不是裸 `loading`）：`usePagedList` 的
//    `loading` 在**触底追加**时也为真，直接传它会让已经显示出来的列表被"加载中"顶掉。
//
// ⚠️ 有数据时**永远渲染 slot** —— 三态只在"没内容可显示"时接管，因此不会改变
//    已有列表的视觉（重构期刻意保持这一点，好让改动可逐页对照验收）。
//
// ⚠️ CSS 只写类选择器（开发约定，见 README）。
defineProps<{
  /** 首屏加载中（触底追加时**不要**传 true —— 见上方说明） */
  loading?: boolean
  /** 失败原因（空串 / 未传 = 无错），一般直接传 `usePagedList` 的 `error` */
  error?: string
  /** 数据是否为空（仅在非 loading、非 error 时才显示空态） */
  empty?: boolean
  /** 自定义文案 */
  loadingText?: string
  emptyText?: string
}>()
</script>

<template>
  <view v-if="loading" class="state-box">
    <text class="state-text">{{ loadingText || '加载中…' }}</text>
  </view>
  <view v-else-if="error" class="state-box">
    <text class="state-text is-err">{{ error }}</text>
  </view>
  <view v-else-if="empty" class="state-box">
    <text class="state-text">{{ emptyText || '暂无数据' }}</text>
  </view>
  <slot v-else />
</template>

<style scoped>
.state-box {
  padding: 40px 16px;
  text-align: center;
}
.state-text {
  font-size: 13px;
  color: var(--text-2);
}
/* 失败态用主题色，与"没有数据"区分开（别让人以为是真的没内容） */
.state-text.is-err {
  color: #c0392b;
}
</style>
