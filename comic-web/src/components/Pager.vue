<script setup lang="ts">
// 分页条：上一页 / **页码输入跳转** / 下一页（2026-10-13）
//
// 抽之前：4 处各写一遍「上一页 + 页码文本 + 下一页」（admin/comics、admin/logs、
// admin/users、search）。本轮按用户要求加上**输入页码回车跳转** —— 原先只能一页页翻。
//
// 约定：
// - **只出事件、不碰状态**：`@change` 给目标页码，由页面决定怎么加载
//   （翻页式页面直接绑 `usePagedList.goPage`）；
// - 输入框回车（confirm / 键盘「前往」）提交；**失焦恢复为当前页码**，防脏值残留；
// - 超界输入自动夹到 `[1, totalPages]`；与当前页相同则不触发 `change`。
//
// ⚠️ 刻意**不做「点击跳转按钮」**：按钮点击会先让输入框失焦（值被恢复），
// 跳转就读不到用户的输入了 —— 故只认 `confirm`（回车 / 键盘「前往」）。
//
// 与 `usePagedList` 的分工：它管状态（页码/竞态/失败回退），本组件只管这一行的交互。
import { ref, watch } from 'vue'

const props = defineProps<{
  /** 当前页（1 起） */
  page: number
  /** 总页数（≥ 1） */
  totalPages: number
}>()

const emit = defineEmits<{ change: [page: number] }>()

/** 输入框里是「正在编辑的页码」，跟随 `page` 同步（翻页成功 / 筛选重置都会更新它） */
const jumpText = ref(String(props.page))
watch(() => props.page, (p) => { jumpText.value = String(p) })

/** 上一页 / 下一页（越界不触发） */
function go(delta: number): void {
  const next = props.page + delta
  if (next < 1 || next > props.totalPages) return
  emit('change', next)
}

/** 回车提交：解析 → 夹紧 → 触发 */
function jump(): void {
  const n = Number.parseInt(jumpText.value, 10)
  if (Number.isNaN(n)) {
    jumpText.value = String(props.page)
    return
  }
  const target = Math.min(Math.max(n, 1), props.totalPages)
  jumpText.value = String(target)   // 先给规范值，不等 watch（避免瞬时脏值）
  if (target !== props.page) emit('change', target)
}

/** 失焦：丢弃编辑中的值（提交请按回车） */
function reset(): void {
  jumpText.value = String(props.page)
}
</script>

<template>
  <div class="pager">
    <button class="btn ghost u-button" :disabled="page <= 1" @click="go(-1)">上一页</button>
    <div class="jump">
      <input
        class="jump-input u-input"
        v-model="jumpText"
        type="number"
        placeholder="页码"
        @keyup.enter="jump"
        @blur="reset"
      />
      <span class="jump-total u-span">/ {{ totalPages }}</span>
    </div>
    <button class="btn ghost u-button" :disabled="page >= totalPages" @click="go(1)">下一页</button>
  </div>
</template>

<style scoped>
.pager {
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 12px;
  margin-top: 22px;
}

.jump { display: flex; align-items: center; gap: 5px; }

/* 页码输入框：窄盒子 + 居中数字（外观与各页 .u-input 的滤镜一致） */
.jump-input {
  width: 52px;
  box-sizing: border-box;
  padding: 5px 4px;
  text-align: center;
  font-size: 14px;
  color: var(--text);
  background: var(--card);
  border: 1px solid var(--border);
  border-radius: 8px;
}

.jump-total { font-size: 14px; color: var(--text-2); }
</style>
