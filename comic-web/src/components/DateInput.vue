<script setup lang="ts">
/**
 * 日期输入（原生 `<input type="date">`）。
 *
 * ⚠️ 样式由**使用方页面**负责（本组件不带视觉样式）：
 *   根元素固定带 `class="date-inp"` 作为钩子 —— 页面的输入框样式规则挂 `.date-inp`。
 */
import { computed } from 'vue'

const props = defineProps<{ modelValue?: string }>()
const emit = defineEmits<{ 'update:modelValue': [value: string] }>()

const val = computed({
  get: () => props.modelValue ?? '',
  set: (v: string) => emit('update:modelValue', v),
})
</script>

<template>
  <input v-model="val" class="date-inp" type="date" />
</template>
