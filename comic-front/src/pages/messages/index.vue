<script setup lang="ts">
// 消息中心独立页（移动端）—— 窄屏点顶栏铃铛直接进这里，不再用下拉浮层。
//
// ⚠️ 数据来自**服务端消息流**（`message` 表 / `GET /api/messages`），本页不读任何本地消息：
// 换台机器打开，看到的是同一份（含已读状态）；定时轮次也在里面（跑的时候是"进行中"条目，
// 跑完变成一条带结果的消息）。
//
// ⚠️ **只有登录用户能看**：进页先自查登录态，没登录直接跳登录页（带 redirect）——
// 不依赖"接口 401 → 请求层清登录态并跳转"那条兜底：那样会先闪一下空页面、还白发一个请求。
// 服务端同样有门（`/api/messages` 要登录），前端这步只是体验层的门。
//
// 为什么要独立页：浮层在手机上宽 340px、`max-width: calc(100vw - 32px)`，贴右边缘后
// 左侧留缝、又盖住页面内容 —— 看着像弹窗；整页才是移动端该有的形态。
import { ref } from 'vue'
import { onHide, onLoad, onShow, onUnload } from '@dcloudio/uni-app'
import { isLoggedIn } from '../../api'
import { kindLabel, statusLabel, fmtMsgTime, paramSummary, useMessageStore } from '../../stores/message'
import { setRoute, useRouter } from '../../utils/router'
import Layout from '../../components/Layout.vue'

const router = useRouter()
const msgStore = useMessageStore()

// 门卫通过前不渲染主体（未登录会被跳走）
const ready = ref(false)

// 进页/回页都拉一次最新（离开期间别的机器、定时器都可能发过消息）
onLoad(() => {
  setRoute('/messages')
  if (!isLoggedIn()) {
    router.replace(`/login?redirect=${encodeURIComponent('/messages')}`)
    return
  }
  ready.value = true
  msgStore.refresh()
})
onShow(() => {
  if (ready.value) msgStore.refresh()
})

// 已读时机：**离开页面**时才整体标，而不是进页就标。两条理由：
//   ① 进页就标的话，顶部「全部已读」按钮（只在有未读时渲染）永远不会出现，等于白放；
//   ② 未读高亮也就看不到了 —— 而「哪条是新的」正是未读标记的全部价值。
// 两个钩子都要挂，覆盖不同的离开路径，避免漏标导致角标残留：
//   - onHide：从抽屉菜单 / 底栏 push 到别的页（本页只隐藏、不销毁）；
//   - onUnload：返回 / redirectTo（本页被销毁）。
onHide(() => msgStore.markAllRead())
onUnload(() => msgStore.markAllRead())
</script>

<template>
  <Layout>
    <view v-if="ready">
      <!-- 顶部操作条：标题 + 全部已读 / 刷新 + 返回。
           ⚠️ `navigationStyle: custom` 没有原生返回箭头，返回入口必须页面自带
           （与 login / admin/logs / reader 的做法一致）。
           ⚠️ 没有「清空」按钮了：消息**在库里**（是历史，别的机器也在看），
              前端删不掉也不该删 —— 不想看就"全部已读"；真要清理走保留策略（services.messages 的 purge）。 -->
      <view class="title-row">
        <view class="section-title">消息</view>
        <view class="title-actions">
          <button v-if="msgStore.unread" class="msg-link u-button" @click="msgStore.markAllRead()">全部已读</button>
          <button class="msg-link u-button" @click="msgStore.refresh()">
            {{ msgStore.loading ? '刷新中…' : '刷新' }}
          </button>
        </view>
        <view class="btn ghost u-a" @click="router.back()">← 返回</view>
      </view>

      <view v-if="msgStore.error" class="empty" style="color:#e23">{{ msgStore.error }}</view>
      <view v-else-if="!msgStore.notices.length" class="empty">
        {{ msgStore.loading ? '加载中…' : '暂无消息' }}
      </view>
      <view v-else class="msg-list">
        <view
          v-for="n in msgStore.notices"
          :key="n.id"
          class="msg-item"
          :class="[n.kind, n.status, { unread: !n.read }]"
          @click="msgStore.markRead(n)"
        >
          <view class="msg-item-head">
            <text class="msg-kind u-span">{{ kindLabel(n.kind) }}</text>
            <text class="msg-status u-span">{{ statusLabel(n) }}</text>
            <text class="msg-time u-span">{{ fmtMsgTime(n.time) }}</text>
          </view>
          <view class="msg-summary">{{ n.title }}</view>
          <view v-if="n.body" class="msg-detail">{{ n.body }}</view>
          <!-- 入参：一眼看出这条消息说的是**哪段时间范围**的数据（起始时间 = since） -->
          <view v-if="paramSummary(n)" class="msg-params">入参：{{ paramSummary(n) }}</view>
          <!-- 触发人 / 源：**收藏更新通知**是采集时自动发的（没有触发人），这行只给任务类消息 -->
          <view v-if="n.kind !== 'update'" class="msg-src">
            触发人：{{ n.username || '—' }}<template v-if="n.source"> · 源：{{ n.source }}</template>
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
.msg-item.import .msg-kind { background: #f3ecff; color: #6b3fa0; }
.msg-item.schedule .msg-kind { background: #e8f4ff; color: #1f6f9c; }
.msg-item.system .msg-kind { background: var(--mute); color: var(--text-2); }
.msg-status { font-size: 12px; font-weight: 700; color: var(--text-2); }
.msg-item.done .msg-status { color: #0a7d3a; }
.msg-item.failed .msg-status { color: #e23; }
.msg-item.running .msg-status { color: #b8860b; }
.msg-time { margin-left: auto; font-size: 12px; color: var(--text-2); }
.msg-summary { font-size: 14px; font-weight: 600; color: var(--text); }
.msg-detail { font-size: 12px; color: var(--text-2); margin-top: 2px; }
/* 入参一行：比正文弱、比"触发人"稍显眼（它是判断"数据时间范围"的关键） */
.msg-params {
  font-size: 12px;
  color: var(--primary-dark);
  background: var(--primary-soft);
  border-radius: 6px;
  padding: 2px 6px;
  margin-top: 4px;
  word-break: break-all;
}
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
