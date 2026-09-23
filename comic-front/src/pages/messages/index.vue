<script setup lang="ts">
// 消息中心独立页（移动端）—— 窄屏点顶栏铃铛直接进这里，不再用下拉浮层。
//
// 数据源与宽屏的下拉面板**完全同一份**（`stores/message.ts`：Pinia + 本地持久化 50 条），
// 本页只是它的另一个渲染出口：面板 = 贴右上角的浮层，本页 = 整页。
// 两者共用 `kindLabel` / `statusLabel` / `fmtMsgTime`，不各写一份。
//
// 为什么要独立页：浮层在手机上宽 340px、`max-width: calc(100vw - 32px)`，贴右边缘后
// 左侧留缝、又盖住页面内容 —— 看着像弹窗；整页才是移动端该有的形态。
import { onHide, onLoad, onUnload } from '@dcloudio/uni-app'
import { kindLabel, statusLabel, fmtMsgTime, useMessageStore } from '../../stores/message'
import { setRoute, useRouter } from '../../utils/router'
import Layout from '../../components/Layout.vue'

const router = useRouter()
const msgStore = useMessageStore()

// 已读时机：**离开页面**时才标，而不是进页就标。两条理由：
//   ① 进页就标的话，顶部「全部已读」按钮（只在有未读时渲染）永远不会出现，等于白放；
//   ② 未读高亮也就看不到了 —— 而「哪条是新的」正是未读标记的全部价值。
// 两个钩子都要挂，覆盖不同的离开路径，避免漏标导致角标残留：
//   - onHide：从抽屉菜单 / 底栏 push 到别的页（本页只隐藏、不销毁）；
//   - onUnload：返回 / redirectTo（本页被销毁）。
onHide(() => msgStore.markAllRead())
onUnload(() => msgStore.markAllRead())

// uni 页面生命周期：登记该页对应的 web 路径（替代 vue-router 的路由状态）
onLoad(() => setRoute('/messages'))
</script>

<template>
  <Layout>
    <view>
      <!-- 顶部操作条：标题 + 全部已读 / 清空 + 返回。
           ⚠️ `navigationStyle: custom` 没有原生返回箭头，返回入口必须页面自带
           （与 login / admin/logs / reader 的做法一致）。 -->
      <view class="title-row">
        <view class="section-title">消息</view>
        <view class="title-actions">
          <button v-if="msgStore.unread" class="msg-link u-button" @click="msgStore.markAllRead()">全部已读</button>
          <button v-if="msgStore.notices.length" class="msg-link u-button" @click="msgStore.clear()">清空</button>
        </view>
        <view class="btn ghost u-a" @click="router.back()">← 返回</view>
      </view>

      <view v-if="!msgStore.notices.length" class="empty">暂无消息</view>
      <view v-else class="msg-list">
        <view
          v-for="n in msgStore.notices"
          :key="n.id"
          class="msg-item"
          :class="[n.kind, n.status, { unread: !n.read }]"
        >
          <view class="msg-item-head">
            <text class="msg-kind u-span">{{ kindLabel(n.kind) }}</text>
            <text class="msg-status u-span">{{ statusLabel(n) }}</text>
            <text class="msg-time u-span">{{ fmtMsgTime(n.time) }}</text>
          </view>
          <view class="msg-summary">{{ n.summary }}</view>
          <view v-if="n.detail" class="msg-detail">{{ n.detail }}</view>
          <view v-if="n.kind !== 'system' && n.source" class="msg-src">
            源：{{ n.source }}<template v-if="n.mode"> · {{ n.mode === 'full' ? '全量' : '增量' }}</template>
          </view>
        </view>
      </view>
    </view>
  </Layout>
</template>

<style scoped>
.title-row {
  display: flex;
  align-items: center;
  gap: 12px;
  flex-wrap: wrap;
  margin: 4px 0 16px;
}
.title-row .section-title { margin: 0; }
.title-actions { display: flex; align-items: center; gap: 12px; margin-left: auto; }
.title-row .btn { text-decoration: none; }

/* 消息条目：视觉语义与顶栏面板里的那份一致（类型标签 / 状态色 / 未读高亮） */
.msg-list {
  display: flex;
  flex-direction: column;
  gap: 10px;
}
.msg-item {
  position: relative;
  background: var(--card);
  border: 1px solid var(--border);
  border-radius: 12px;
  padding: 12px 14px;
  box-shadow: var(--shadow);
}
.msg-item.unread { border-color: var(--primary); }
.msg-item.unread::before {
  content: '';
  position: absolute;
  left: 5px;
  top: 50%;
  transform: translateY(-50%);
  width: 6px;
  height: 6px;
  border-radius: 50%;
  background: var(--primary);
}
.msg-item-head { display: flex; align-items: center; gap: 8px; margin-bottom: 4px; }
.msg-kind {
  font-size: 12px;
  font-weight: 700;
  padding: 1px 8px;
  border-radius: 999px;
  background: var(--primary-soft);
  color: var(--primary-dark);
}
.msg-item.transfer .msg-kind { background: #eef6ff; color: #2b6cb0; }
.msg-item.inspect .msg-kind { background: #eef7ec; color: #2f6d1f; }
.msg-item.heal .msg-kind { background: #fff4e5; color: #a15c00; }
.msg-item.system .msg-kind { background: var(--mute); color: var(--text-2); }
.msg-status { font-size: 12px; font-weight: 700; color: var(--text-2); }
.msg-item.done .msg-status { color: #0a7d3a; }
.msg-item.failed .msg-status { color: #e23; }
.msg-item.running .msg-status { color: #b8860b; }
.msg-time { margin-left: auto; font-size: 12px; color: var(--text-2); }
.msg-summary { font-size: 14px; font-weight: 600; color: var(--text); }
.msg-detail { font-size: 12px; color: var(--text-2); margin-top: 2px; }
.msg-src { font-size: 12px; color: var(--text-2); margin-top: 2px; }

.msg-link {
  border: none;
  background: none;
  color: var(--primary);
  font-size: 13px;
  font-weight: 600;
  cursor: pointer;
  padding: 0;
}
.msg-link:hover { color: var(--primary-dark); text-decoration: underline; }
</style>
