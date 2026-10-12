<script setup lang="ts">
// 用户头像：有上传头像（`url`）显示图片，否则显示昵称首字的渐变圆。
// 纯展示组件（无 v-model）；尺寸由 `size` 传入（px），字号随尺寸缩放。
import { computed } from 'vue'

const props = defineProps<{
  /** 头像 URL（'' / 缺省 = 未上传 → 首字母头像） */
  url?: string
  /** 昵称（取首字做默认头像；缺省显示「我」） */
  name?: string
  /** 直径（px），默认 36 */
  size?: number
}>()

const px = computed(() => `${props.size ?? 36}px`)
const fontSize = computed(() => `${Math.round((props.size ?? 36) * 0.42)}px`)
const letter = computed(() => (props.name || '我').slice(0, 1))
</script>

<template>
  <view class="uavatar" :style="{ width: px, height: px, fontSize: fontSize }">
    <image v-if="url" class="uavatar-img" :src="url" mode="aspectFill" :alt="name || '头像'" />
    <text v-else class="uavatar-text u-span">{{ letter }}</text>
  </view>
</template>

<style scoped>
.uavatar {
  border-radius: 50%;
  background: linear-gradient(135deg, var(--primary), var(--accent));
  color: #fff;
  font-weight: 800;
  display: flex;
  align-items: center;
  justify-content: center;
  flex: none;
  overflow: hidden;
}
.uavatar-img { width: 100%; height: 100%; display: block; }
</style>
