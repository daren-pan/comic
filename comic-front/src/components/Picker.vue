<script setup lang="ts">
/**
 * 下拉选择 —— `<select>` 的跨端替身。
 *
 * 为什么必须换：**小程序没有 `<select>` / `<option>` 组件**，`<select>` 会被原样写进 WXML
 * 而小程序不认识，整块筛选栏渲染不出来。uni 的对应物是 `<picker mode="selector">`，
 * 但它只接受「字符串数组 + 下标」，而页面里绑定的是业务值（`'INFO'` / `'zaimanhua'` / `20`）。
 * 这个组件做两件事：
 *   1. `{value,label}[]` → `range: string[]`，并把当前值换算成下标（找不到落回 0，与原生
 *      `<select>` 无匹配项时回落到第一项的行为一致）；
 *   2. 选中后把下标换回业务值，`emit('update:modelValue', value)` + `emit('change')`，
 *      于是页面可以照旧写 `@change="search"`。
 *
 * ⚠️ **自定义组件上不能写 `v-model`** —— 小程序端编译器会直接报
 * 「v-model can only be used on <input>, <textarea> and <select> elements」。
 * 调用方一律用 `:model-value` + `@update:model-value`（本组件同理，见 DateInput 的用法）。
 *
 * 视觉：本组件自带一套盒子样式（边框/圆角/内边距），页面只需给根元素一个宽度类
 * （如 `.filters .u-select { min-width: 88px }`）—— 不要在外层再画一遍边框，否则双边框。
 */
import { computed } from 'vue'
import type { PickerOption } from '../types'

const props = defineProps<{
  modelValue: string | number
  options: PickerOption[]
  disabled?: boolean
}>()

const emit = defineEmits<{
  'update:modelValue': [value: string | number]
  change: []
}>()

const labels = computed(() => props.options.map((o) => o.label))

const index = computed(() => {
  const i = props.options.findIndex((o) => String(o.value) === String(props.modelValue))
  return i < 0 ? 0 : i
})

const current = computed(() => props.options[index.value]?.label ?? '')

function onPick(e: { detail: { value: string | number } }) {
  const opt = props.options[Number(e.detail.value)]
  if (!opt) return
  emit('update:modelValue', opt.value)
  emit('change')
}
</script>

<template>
  <picker
    mode="selector"
    :range="labels"
    :value="index"
    :disabled="!!disabled"
    @change="onPick"
  >
    <view class="picker-box">
      <text class="picker-text">{{ current }}</text>
      <text class="picker-arrow">▾</text>
    </view>
  </picker>
</template>

<style scoped>
.picker-box {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 6px;
  min-width: 84px;
  font-size: 13px;
  color: var(--text);
  background: #fff;
  border: 1px solid var(--border);
  border-radius: 8px;
  padding: 6px 8px;
}
.picker-text { overflow: hidden; white-space: nowrap; text-overflow: ellipsis; }
.picker-arrow { color: var(--text-2); font-size: 11px; flex-shrink: 0; }
</style>
