<script setup lang="ts">
/**
 * 筛选条 —— 标签（下拉单选）+ 排序，供「分类浏览」与「热度排行」两页共用。
 *
 * 为什么抽成组件：这两页原来各写一套（分类页是 30 个标签平铺成一片 chip，排行榜是
 * 每个标签单独一个区块），条件一改要动两处、还容易走样。抽出来后**只有一份**，
 * 改条件/加排序项只改这里。
 *
 * 标签用 `Picker` 而不是 chip 平铺：库内 30 个标签平铺会占掉整屏、把结果推到下面，
 * 下拉只占一行。小程序没有 `<select>`，所以必须走 Picker（见 components/Picker.vue）。
 *
 * ⚠️ 自定义组件上不能写 `v-model`（小程序编译报错）→ 这里用 `:model-value` +
 * `@update:model-value`，对外的 props/emits 也照此命名，调用方同样不能对它写 `v-model`。
 */
import { computed } from 'vue'
import Picker from './Picker.vue'
import type { CategoryCount, PickerOption } from '../types'
import type { ComicSort } from '../api'

const props = defineProps<{
  /** 当前标签名（'全部' = 不过滤） */
  category: string
  /** 当前排序 */
  sort: ComicSort
  /** 标签列表（来自 /api/categories，含各自作品数） */
  categories: CategoryCount[]
}>()

const emit = defineEmits<{
  'update:category': [value: string]
  'update:sort': [value: ComicSort]
}>()

/**
 * 标签下拉选项：带作品数，形如「恋爱（42）」——省得再单列一排计数。
 *
 * ⚠️ **「全部」不带数字**：后端 `/api/categories` 给「全部」的 count 是**各标签计数之和**
 * （`sum(i["count"] for i in items)`），同一部作品挂 3 个标签就被计 3 次，与真实作品数不符
 * （实测 119 vs 实际 52）。显示出来会和排行页的「共 N 部」打架，所以只对它省略数字。
 */
const options = computed<PickerOption[]>(() =>
  props.categories.map((c) => ({
    value: c.name,
    label: c.name === '全部' ? '全部' : `${c.name}（${c.count}）`,
  })),
)

/** 排序项：热度（默认）→ 收藏 → 更新时间。文案与后端 sort 取值一一对应。 */
const SORTS: { value: ComicSort; label: string }[] = [
  { value: 'views', label: '最热' },
  { value: 'favorites', label: '收藏最多' },
  { value: 'updated', label: '最新更新' },
]

function onCategory(v: string | number) {
  emit('update:category', String(v))
}
</script>

<template>
  <view class="filter-bar">
    <view class="fb-field">
      <text class="fb-label u-span">标签</text>
      <Picker class="fb-select" :model-value="category" :options="options" @update:model-value="onCategory" />
    </view>

    <view class="fb-field">
      <text class="fb-label u-span">排序</text>
      <button
        v-for="s in SORTS"
        :key="s.value"
        class="fb-btn u-button"
        :class="{ on: sort === s.value }"
        @click="emit('update:sort', s.value)"
      >{{ s.label }}</button>
    </view>
  </view>
</template>

<style scoped>
.filter-bar {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 10px 18px;
  padding: 10px 14px;
  background: var(--card);
  border: 1px solid var(--border);
  border-radius: var(--radius);
}

.fb-field { display: flex; align-items: center; gap: 8px; flex-wrap: wrap; }
.fb-label { font-size: 13px; color: var(--text-2); flex: none; }

/* Picker 自带盒子样式，这里只给宽度（不要在外层再画边框，否则双边框） */
.fb-select { min-width: 132px; }

.fb-btn {
  border: 1px solid var(--border);
  background: var(--bg);
  padding: 5px 12px;
  border-radius: 8px;
  font-size: 13px;
  cursor: pointer;
  color: var(--text-2);
  transition: all 0.15s;
}
.fb-btn:hover { border-color: var(--primary); color: var(--primary); }
.fb-btn.on { background: var(--primary-soft); color: var(--primary); border-color: var(--primary); font-weight: 600; }
</style>
