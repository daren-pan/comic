<script setup lang="ts">
/**
 * 日期输入（H5 用原生控件，其它端降级为文本输入）。
 *
 * 为什么不能直接用 `<input type="date">`：
 *   uni 的 Input 组件对 `type` 有**白名单**（text / number / idcard / digit / password / tel），
 *   白名单外的值一律被**强制成 text**（源码：`INPUT_TYPES.includes(props.type) ? props.type : "text"`）
 *   —— 原生日期选择器就此消失，只剩一个普通文本框。
 *
 * H5 端：用**渲染函数**直接产出原生 `<input type="date">`。
 *   模板里的 `<input>` 会被 uni 编译成内置组件（easycom 把 `_resolveComponent("input")`
 *   替换成 @dcloudio/uni-h5 的 Input），而 `h('input')` 是**运行时**调用、不经模板编译 ——
 *   Vue 对字符串 tag 直接创建原生元素，因此能拿到真正的原生控件。
 * 其它端：退回 uni 的文本输入（管理台以 H5 为主；小程序/App 端仍可手输 YYYY-MM-DD）。
 *
 * ⚠️ 样式由**使用方页面**负责（本组件不带视觉样式）：
 *   根元素固定带 `class="date-inp"` 作为钩子。页面里原有的 `input` 选择器会被 uni 改写
 *   （`.row-inputs input` → `.row-inputs uni-input`），**匹配不到这个原生 input**，
 *   所以页面的输入框样式规则要额外挂上 `.date-inp`。
 *   （作用域：子组件根元素会同时带上父页面的 `data-v-*`，故页面 scoped 样式能命中它。）
 */
import { computed } from 'vue'
// #ifdef H5
import { defineComponent, h } from 'vue'

const NativeDateInput = defineComponent({
  name: 'NativeDateInput',
  props: { modelValue: { type: String, default: '' } },
  emits: ['update:modelValue'],
  setup(props, { emit }) {
    const onInput = (e: Event) => emit('update:modelValue', (e.target as HTMLInputElement).value)
    return () =>
      h('input', {
        class: 'date-inp',
        type: 'date',
        value: props.modelValue,
        onInput,
        onChange: onInput,
      })
  },
})
// #endif

const props = defineProps<{ modelValue?: string }>()
const emit = defineEmits<{ 'update:modelValue': [value: string] }>()

const val = computed({
  get: () => props.modelValue ?? '',
  set: (v: string) => emit('update:modelValue', v),
})
</script>

<template>
  <!-- #ifdef H5 -->
  <NativeDateInput v-model="val" />
  <!-- #endif -->
  <!-- #ifndef H5 -->
  <input v-model="val" class="date-inp u-input" type="text" placeholder="YYYY-MM-DD" />
  <!-- #endif -->
</template>
