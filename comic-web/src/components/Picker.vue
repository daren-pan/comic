<script setup lang="ts">
/**
 * 下拉选择 —— 原生 `<select>` 封装。
 *
 * 调用方传 `{value,label}[]`（业务值可能是字符串或数字），本组件把「业务值 ↔ 下标」
 * 的换算收敛在一处；选中后 `emit('update:modelValue', value)` + `emit('change')`，
 * 于是页面可以照旧写 `@change="search"`（与 comic-front 的 Picker 接口完全一致）。
 *
 * ⚠️ **自定义组件上不写 `v-model`** —— 全站统一用 `:model-value` + `@update:model-value`
 * 显式写法（不用语法糖）。
 *
 * 视觉：自带盒子样式（边框/圆角/内边距 + 自绘箭头 ▾，随主题变量走）；
 * 调用方只需给宽度类（如 `class="u-select"` + 页面里 `.pager .u-select { min-width: 72px }`）。
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

/** 当前值 → 下标（找不到落回 0，与原生 select 无匹配项时回落到第一项的行为一致） */
const index = computed(() => {
  const i = props.options.findIndex((o) => String(o.value) === String(props.modelValue))
  return i < 0 ? 0 : i
})

function onPick(e: Event) {
  const opt = props.options[Number((e.target as HTMLSelectElement).value)]
  if (!opt) return
  emit('update:modelValue', opt.value)
  emit('change')
}
</script>

<template>
  <div class="picker-wrap">
    <select class="picker-native" :value="index" :disabled="disabled" @change="onPick">
      <option v-for="(o, i) in options" :key="`${o.value}`" :value="i">{{ o.label }}</option>
    </select>
    <span class="picker-arrow">▾</span>
  </div>
</template>

<style scoped>
.picker-wrap {
  position: relative;
  display: inline-flex;
  align-items: center;
  min-width: 84px;
  font-size: 13px;
  color: var(--text);
  background: var(--card);
  border: 1px solid var(--border);
  border-radius: 8px;
}
.picker-native {
  appearance: none;
  -webkit-appearance: none;
  width: 100%;
  font: inherit;
  color: inherit;
  background: transparent;
  border: none;
  outline: none;
  padding: 6px 22px 6px 8px;
  cursor: pointer;
}
.picker-native:disabled { cursor: not-allowed; opacity: 0.5; }
.picker-arrow {
  position: absolute;
  right: 7px;
  color: var(--text-2);
  font-size: 11px;
  pointer-events: none;
}
</style>
