<script setup lang="ts">
import type { Comic } from '../types'
import { useRouter } from '../utils/router'

// time：可选角标（如「3 小时前」），用于「最近更新」等需要体现时间维度的列表页；
// 不传时卡片与原先完全一致（首页 / 分类页 / 搜索结果均不受影响）。
defineProps<{ comic: Comic; time?: string }>()

// 卡片整体可点：替代 comic-web 的 <RouterLink>，跳详情页
const router = useRouter()
</script>

<template>
  <view class="card u-a" @click="router.push(`/comic/${comic.id}`)">
    <view class="cover">
      <image mode="aspectFill" class="u-img" :src="comic.cover" :alt="comic.title" loading="lazy" />
      <text class="status u-span" :class="{ done: comic.status === '已完结' }">{{ comic.status }}</text>
      <text v-if="time" class="time u-span">{{ time }}</text>
    </view>
    <view class="info">
      <view class="title u-h3">{{ comic.title }}</view>
      <view class="meta u-p">{{ comic.author }}</view>
      <view class="update u-p">{{ comic.latestChapterTitle }}</view>
    </view>
  </view>
</template>

<style scoped>
.card {
  display: block;
  background: var(--card);
  border-radius: var(--radius);
  overflow: hidden;
  box-shadow: var(--shadow);
  transition: transform 0.18s, box-shadow 0.18s;
  text-decoration: none;
  color: inherit;
}
.card:hover { transform: translateY(-4px); box-shadow: var(--shadow-hover); }

/* 封面 3:4 比例盒：**不用 `aspect-ratio`** —— 小程序 WebView 视基础库/系统版本而定
   （需 Chrome 88+ / iOS 15+），改用「高度 0 + padding-bottom 撑比例」这一到处都能用的写法
   （padding 的百分比按**包含块宽度**解析，正好得到宽度驱动的等比高度）。
   ⚠️ absolute 子元素的包含块是祖先的 padding box，故 .status / .time 的 top/left 定位不受影响。 */
.cover { position: relative; height: 0; padding-bottom: 133.33%; background: #eee; overflow: hidden; }
.cover .u-img { position: absolute; top: 0; left: 0; width: 100%; height: 100%; object-fit: cover; display: block; }

.status {
  position: absolute;
  top: 8px;
  left: 8px;
  font-size: 11px;
  padding: 2px 8px;
  border-radius: 999px;
  background: rgba(255, 90, 54, 0.92);
  color: #fff;
  font-weight: 700;
}
.status.done { background: rgba(90, 90, 90, 0.85); }

.time {
  position: absolute;
  top: 8px;
  right: 8px;
  font-size: 11px;
  padding: 2px 8px;
  border-radius: 999px;
  background: rgba(0, 0, 0, 0.55);
  color: #fff;
  font-weight: 600;
  backdrop-filter: blur(2px);
}

.info { padding: 10px 12px 12px; }
.title {
  margin: 0;
  font-size: 15px;
  font-weight: 700;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}
.meta { margin: 2px 0 0; font-size: 12px; color: var(--text-2); }
.update { margin: 6px 0 0; font-size: 12px; color: var(--primary); white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }

/* 手机（≤560px）三列：列宽只剩 ~110px，字号 / 内边距按比例收紧，否则标题被截得只剩两三个字。
   断点与各页 .grid 的媒体查询一致（首页 / 最近更新 / 分类 / 我的收藏）。 */
@media (max-width: 560px) {
  .info { padding: 7px 8px 9px; }
  .title { font-size: 13px; }
  .meta, .update { font-size: 11px; }
  /* 作者名原先没截断（行内没有 ellipsis / nowrap），窄卡片下会把行撑破 */
  .meta { white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
  .update { margin-top: 4px; }
  .status { top: 5px; left: 5px; font-size: 10px; padding: 1px 6px; }
  .time { top: 5px; right: 5px; font-size: 10px; padding: 1px 6px; }
}
</style>
