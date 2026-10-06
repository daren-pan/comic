<script setup lang="ts">
// 管理台三个页面的**同一栏选项卡**：采集管理 / 定时任务 / 运行日志 —— 点选项切换。
//
// 为什么是"导航式选项卡"而不是把三页合并成一页做页内切换：
// 三页各有独立的页面逻辑与状态（数据源表单 / cron 与运行态 / 日志筛选与分页），
// 合并会把这些状态搅在一起，还会丢掉可直达、可分享的地址（`#/admin/schedule` 等，
// 见 README 的页面对照表）。选项卡只负责"切换看哪一栏"，页面照旧各自独立。
//
// ⚠️ 用 `replace` 而不是 `push`：来回点选项不该在页面栈里堆一层层历史（否则"返回"
// 要点很多次才退得出去）。
//
// 用法：各页在标题栏位置放 `<AdminTabs current="admin|schedule|logs" />` —— 不再各写
// "⏰ 定时任务 / 📄 运行日志"按钮与"← 返回采集管理"链接（那些就是本组件的三个选项）。
import { useRouter } from '../utils/router'

type TabKey = 'admin' | 'schedule' | 'logs'

const props = defineProps<{ current: TabKey }>()
const router = useRouter()

const TABS: { key: TabKey; label: string; path: string }[] = [
  { key: 'admin', label: '采集管理', path: '/admin' },
  { key: 'schedule', label: '定时任务', path: '/admin/schedule' },
  { key: 'logs', label: '运行日志', path: '/admin/logs' },
]

function go(tab: { key: TabKey; path: string }) {
  if (tab.key === props.current) return   // 点当前项：不重复导航
  router.replace(tab.path)
}
</script>

<template>
  <view class="admin-tabs">
    <view
      v-for="t in TABS"
      :key="t.key"
      class="tab"
      :class="{ on: t.key === current }"
      :title="t.label"
      @click="go(t)"
    >
      <text class="u-span">{{ t.label }}</text>
    </view>
  </view>
</template>

<style scoped>
/* 分段控件：选中项用主色实底（与全站按钮/标签的视觉一致）。
   ⚠️ 只画类选择器（uni 会把标签改写成 uni-view，用标签选择器会失配）。 */
.admin-tabs {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
}
.tab {
  padding: 5px 14px;
  border: 1px solid var(--border);
  border-radius: 999px;
  background: var(--card);
  color: var(--text-2);
  font-size: 13px;
  cursor: pointer;
}
.tab.on {
  background: var(--primary);
  border-color: var(--primary);
  color: #fff;
  font-weight: 700;
}
/* 窄屏（≤560px，与 Layout 的收紧档一致） */
@media (max-width: 560px) {
  .tab { padding: 4px 10px; font-size: 12px; }
}
</style>
