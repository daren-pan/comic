<script setup lang="ts">
import { ref, onMounted, onBeforeUnmount, watch } from 'vue'
import { storeToRefs } from 'pinia'
import { useRoute, useRouter } from 'vue-router'
import { backendAlive } from './api'
import { useUserStore } from './stores/user'
import { useMessageStore } from './stores/message'
import type { NoticeItem, NoticeKind } from './stores/message'

const route = useRoute()
const router = useRouter()

const keyword = ref('')
const showMenu = ref(false)
const backend = ref<boolean | null>(null)

// 登录态：全局唯一来源 = Pinia user store（登录/登出/401 后自动同步，无需路由 hack）
const userStore = useUserStore()
const { isLoggedIn: logged, user } = storeToRefs(userStore)

// 消息中心：采集/转存任务结果 + 系统消息（顶栏入口，点击展开面板）
const msgStore = useMessageStore()
const showMsg = ref(false)

function toggleMsg() {
  showMsg.value = !showMsg.value
  if (showMsg.value) msgStore.markAllRead() // 展开即视为已读
}
function closeMsg() {
  showMsg.value = false
}
function onDocClick() {
  closeMsg() // 点击面板外部关闭
}

function kindLabel(k: NoticeKind): string {
  return k === 'sync'
    ? '采集'
    : k === 'transfer'
      ? '转存'
      : k === 'inspect'
        ? '巡检'
        : '系统'
}
function statusLabel(n: NoticeItem): string {
  if (n.status === 'running') return '运行中'
  if (n.status === 'done') return '完成'
  if (n.status === 'failed') return '失败'
  return '通知'
}
function fmtMsgTime(iso: string): string {
  const d = new Date(iso)
  const pad = (n: number) => String(n).padStart(2, '0')
  return `${pad(d.getMonth() + 1)}-${pad(d.getDate())} ${pad(d.getHours())}:${pad(d.getMinutes())}`
}

onMounted(async () => {
  userStore.init() // 开始监听 api 层 'auth:changed' 事件，同步登录态
  msgStore.init()  // 载入持久化的历史消息
  document.addEventListener('click', onDocClick)
  backend.value = await backendAlive()
})

onBeforeUnmount(() => {
  document.removeEventListener('click', onDocClick)
})

function onSearch() {
  const k = keyword.value.trim()
  router.push({ path: '/search', query: k ? { keyword: k } : {} })
  keyword.value = ''
  showMenu.value = false
}

function onLogout() {
  userStore.logout() // clearAuth + 广播事件 → store 自动同步 → 顶栏复位
  router.push('/')
}

// 路由切换时收起移动端菜单与消息面板（登录态已由 store 自动同步，无需再手动刷新）
watch(() => route.path, () => {
  showMenu.value = false
  showMsg.value = false
})
</script>

<template>
  <header class="nav">
    <div class="container nav-inner">
      <RouterLink to="/" class="logo">
        <span class="logo-mark">漫</span>
        <span class="logo-text">漫阅<em>COMIC</em></span>
      </RouterLink>

      <nav class="nav-links">
        <RouterLink to="/" :class="{ on: route.path === '/' }">首页</RouterLink>
        <RouterLink to="/search" :class="{ on: route.path === '/search' }">分类</RouterLink>
        <RouterLink to="/latest" :class="{ on: route.path === '/latest' }">最近更新</RouterLink>
        <RouterLink to="/rank" :class="{ on: route.path === '/rank' }">排行</RouterLink>
        <RouterLink to="/me" :class="{ on: route.path === '/me' }">我的</RouterLink>
        <RouterLink to="/admin" :class="{ on: route.path === '/admin' }">管理</RouterLink>
      </nav>

      <div class="nav-right">
        <form class="search-box" @submit.prevent="onSearch">
          <input v-model="keyword" type="text" placeholder="搜索漫画 / 作者 / 标签" />
          <button type="submit" aria-label="搜索">🔍</button>
        </form>

        <!-- 消息中心：采集/转存任务结果 + 系统消息（点击展开） -->
        <div class="msg-wrap">
          <button class="msg-btn" :class="{ on: showMsg }" @click.stop="toggleMsg" title="消息">
            <span class="msg-icon">🔔</span>
            <span v-if="msgStore.unread" class="msg-badge">{{ msgStore.unread > 99 ? '99+' : msgStore.unread }}</span>
          </button>
          <transition name="drop">
            <div v-if="showMsg" class="msg-panel" @click.stop>
              <div class="msg-head">
                <span class="msg-title">消息</span>
                <div class="msg-actions">
                  <button v-if="msgStore.unread" class="msg-link" @click="msgStore.markAllRead()">全部已读</button>
                  <button v-if="msgStore.notices.length" class="msg-link" @click="msgStore.clear()">清空</button>
                </div>
              </div>
              <div v-if="!msgStore.notices.length" class="msg-empty">暂无消息</div>
              <div v-else class="msg-list">
                <div
                  v-for="n in msgStore.notices"
                  :key="n.id"
                  class="msg-item"
                  :class="[n.kind, n.status, { unread: !n.read }]"
                >
                  <div class="msg-item-head">
                    <span class="msg-kind">{{ kindLabel(n.kind) }}</span>
                    <span class="msg-status">{{ statusLabel(n) }}</span>
                    <span class="msg-time">{{ fmtMsgTime(n.time) }}</span>
                  </div>
                  <div class="msg-summary">{{ n.summary }}</div>
                  <div v-if="n.detail" class="msg-detail">{{ n.detail }}</div>
                  <div v-if="n.kind !== 'system' && n.source" class="msg-src">
                    源：{{ n.source }}<template v-if="n.mode"> · {{ n.mode === 'full' ? '全量' : '增量' }}</template>
                  </div>
                </div>
              </div>
            </div>
          </transition>
        </div>

        <template v-if="logged">
          <button class="user-chip" @click="router.push('/me')" title="我的书架">
            <span class="avatar">{{ (user?.nickname || '我').slice(0, 1) }}</span>
            {{ user?.nickname || user?.username }}
          </button>
          <button class="logout" @click="onLogout">退出</button>
        </template>
        <RouterLink v-else to="/login" class="login-link">登录</RouterLink>
        <button class="menu-btn" @click="showMenu = !showMenu" aria-label="菜单">☰</button>
      </div>
    </div>

    <!-- 移动端菜单 -->
    <div v-if="showMenu" class="mobile-menu">
      <RouterLink to="/" @click="showMenu = false">首页</RouterLink>
      <RouterLink to="/search" @click="showMenu = false">分类</RouterLink>
      <RouterLink to="/latest" @click="showMenu = false">最近更新</RouterLink>
      <RouterLink to="/rank" @click="showMenu = false">排行</RouterLink>
      <RouterLink to="/me" @click="showMenu = false">我的收藏与历史</RouterLink>
      <RouterLink to="/admin" @click="showMenu = false">采集管理</RouterLink>
      <RouterLink v-if="!logged" to="/login" @click="showMenu = false">登录</RouterLink>
      <a v-else href="#" @click.prevent="onLogout(); showMenu = false">退出登录</a>
    </div>
  </header>

  <main class="container page">
    <RouterView />
  </main>

  <footer class="footer">
    <div class="container">
      <p>漫阅 Comic — 漫画聚合阅读平台
        <span v-if="backend === true" class="src-tag real">● 已连接采集服务（真实数据）</span>
        <span v-else class="src-tag">● 演示模式（本地 mock 数据）</span>
      </p>
      <p class="tip">仅收录已授权 / 开放版权 / 公共领域内容 · 尊重版权，支持正版</p>
    </div>
  </footer>

  <!-- 任务结果 toast：采集/转存执行完毕提示（全站可见） -->
  <transition name="toast">
    <div v-if="msgStore.toast" class="toast" :class="msgStore.toast.status">
      <div class="toast-head">
        <span class="toast-title">{{ kindLabel(msgStore.toast.kind) }} · {{ statusLabel(msgStore.toast) }}</span>
        <button class="toast-close" @click="msgStore.dismissToast()">×</button>
      </div>
      <div class="toast-text">{{ msgStore.toast.summary }}</div>
      <div v-if="msgStore.toast.detail" class="toast-detail">{{ msgStore.toast.detail }}</div>
    </div>
  </transition>
</template>

<style scoped>
.nav {
  position: sticky;
  top: 0;
  z-index: 100;
  background: #fff;
  border-bottom: 1px solid var(--border);
  box-shadow: var(--shadow);
}
.nav-inner {
  display: flex;
  align-items: center;
  gap: 24px;
  height: 60px;
}
.logo { display: flex; align-items: center; gap: 8px; flex-shrink: 0; }
.logo-mark {
  width: 34px; height: 34px;
  border-radius: 9px;
  background: linear-gradient(135deg, var(--primary), var(--accent));
  color: #fff;
  font-weight: 800;
  font-size: 19px;
  display: flex; align-items: center; justify-content: center;
}
.logo-text { font-weight: 800; font-size: 19px; }
.logo-text em { font-style: normal; font-size: 11px; color: var(--primary); margin-left: 4px; letter-spacing: 1px; }

.nav-links { display: flex; gap: 2px; flex: 1; min-width: 0; }
.nav-links a {
  padding: 6px 10px;
  border-radius: 8px;
  font-weight: 600;
  color: var(--text-2);
  white-space: nowrap;
  flex-shrink: 0;
  transition: all 0.15s;
}
.nav-links a:hover { color: var(--primary); background: var(--primary-soft); }
.nav-links a.on { color: var(--primary); background: var(--primary-soft); }

.nav-right { display: flex; align-items: center; gap: 10px; }
.search-box { display: flex; align-items: center; background: var(--bg); border: 1px solid var(--border); border-radius: 999px; padding: 0 4px 0 14px; height: 36px; width: 220px; min-width: 150px; flex-shrink: 1; transition: border 0.15s; }
.search-box:focus-within { border-color: var(--primary); background: #fff; }
/* min-width:0 让 input 可以真正收缩（默认 auto 会按默认字符宽度撑住，把右侧按钮压扁）； */
.search-box input { border: none; outline: none; background: transparent; flex: 1 1 auto; min-width: 0; font-size: 13px; color: var(--text); }
/* 按钮固定 28×28 不被压缩，圆形图标居中 —— 否则窄容器下会被 flex 压成扁椭圆 */
.search-box button { border: none; background: var(--primary); color: #fff; width: 28px; height: 28px; flex: 0 0 28px; border-radius: 999px; cursor: pointer; font-size: 12px; display: inline-flex; align-items: center; justify-content: center; line-height: 1; padding: 0; }

.menu-btn { display: none; border: none; background: none; font-size: 20px; cursor: pointer; color: var(--text); }

.user-chip {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  border: 1px solid var(--border);
  background: #fff;
  border-radius: 999px;
  padding: 4px 12px 4px 4px;
  font-size: 13px;
  font-weight: 600;
  cursor: pointer;
  color: var(--text);
  max-width: 140px;
}
.user-chip:hover { border-color: var(--primary); color: var(--primary); }
.avatar {
  width: 26px; height: 26px;
  border-radius: 50%;
  background: linear-gradient(135deg, var(--primary), var(--accent));
  color: #fff;
  font-size: 13px; font-weight: 800;
  display: flex; align-items: center; justify-content: center;
  flex-shrink: 0;
}
.user-chip span:last-child { white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.logout {
  border: none;
  background: none;
  color: var(--text-2);
  font-size: 13px;
  cursor: pointer;
  padding: 4px 6px;
}
.logout:hover { color: #e23; }
.login-link {
  padding: 6px 16px;
  border-radius: 999px;
  background: var(--primary);
  color: #fff;
  font-size: 13px;
  font-weight: 600;
}
.login-link:hover { background: var(--primary-dark); }

.mobile-menu {
  display: none;
  padding: 8px 16px 14px;
  border-top: 1px solid var(--border);
  background: #fff;
  flex-direction: column;
}
.mobile-menu a { padding: 10px 8px; border-radius: 8px; font-weight: 600; color: var(--text-2); display: flex; justify-content: space-between; }
.mobile-menu a.on { color: var(--primary); background: var(--primary-soft); }
.mobile-menu span { color: #bbb; font-size: 13px; }

.footer {
  border-top: 1px solid var(--border);
  background: #fff;
  padding: 22px 0 30px;
  text-align: center;
  color: var(--text-2);
  font-size: 13px;
}
.footer .tip { margin-top: 4px; font-size: 12px; color: #b5aca2; }
.src-tag { margin-left: 8px; font-size: 12px; color: var(--text-2); background: var(--bg); border: 1px solid var(--border); border-radius: 999px; padding: 2px 10px; }
.src-tag.real { color: #0a7d3a; background: #e9f7ee; border-color: #b7e5c8; }

/* ---- 消息中心 ---- */
.msg-wrap { position: relative; flex-shrink: 0; }
.msg-btn {
  position: relative;
  width: 36px; height: 36px;
  display: inline-flex; align-items: center; justify-content: center;
  border: 1px solid var(--border);
  background: #fff;
  border-radius: 50%;
  cursor: pointer;
  transition: all 0.15s;
}
.msg-btn:hover, .msg-btn.on { border-color: var(--primary); background: var(--primary-soft); }
.msg-icon { font-size: 16px; line-height: 1; }
.msg-badge {
  position: absolute; top: -4px; right: -4px;
  min-width: 16px; height: 16px; padding: 0 4px;
  background: var(--primary); color: #fff;
  font-size: 10px; font-weight: 700; line-height: 16px;
  border-radius: 999px; text-align: center;
  box-shadow: 0 0 0 2px #fff;
}
.msg-panel {
  position: absolute; top: 46px; right: 0;
  width: 340px; max-width: calc(100vw - 32px);
  max-height: 440px;
  background: #fff;
  border: 1px solid var(--border);
  border-radius: 14px;
  box-shadow: var(--shadow-hover);
  z-index: 200;
  display: flex; flex-direction: column;
  overflow: hidden;
}
.msg-head {
  display: flex; align-items: center; justify-content: space-between;
  padding: 12px 14px; border-bottom: 1px solid var(--border);
}
.msg-title { font-weight: 800; font-size: 15px; }
.msg-actions { display: flex; gap: 10px; }
.msg-link { border: none; background: none; color: var(--primary); font-size: 12px; font-weight: 600; cursor: pointer; padding: 0; }
.msg-link:hover { color: var(--primary-dark); text-decoration: underline; }
.msg-empty { padding: 36px 0; text-align: center; color: var(--text-2); font-size: 14px; }
.msg-list { overflow-y: auto; }
.msg-item { padding: 10px 14px; border-bottom: 1px solid var(--border); position: relative; }
.msg-item:last-child { border-bottom: none; }
.msg-item.unread { background: var(--primary-soft); }
.msg-item.unread::before {
  content: ''; position: absolute; left: 6px; top: 50%; transform: translateY(-50%);
  width: 6px; height: 6px; border-radius: 50%; background: var(--primary);
}
.msg-item-head { display: flex; align-items: center; gap: 8px; margin-bottom: 3px; }
.msg-kind { font-size: 12px; font-weight: 700; padding: 1px 8px; border-radius: 999px; background: var(--primary-soft); color: var(--primary-dark); }
.msg-item.transfer .msg-kind { background: #eef6ff; color: #2b6cb0; }
.msg-item.inspect .msg-kind { background: #eef7ec; color: #2f6d1f; }
.msg-item.system .msg-kind { background: #f0f0f0; color: var(--text-2); }
.msg-status { font-size: 12px; font-weight: 700; }
.msg-item .msg-status { color: var(--text-2); }
.msg-item.done .msg-status { color: #0a7d3a; }
.msg-item.failed .msg-status { color: #e23; }
.msg-item.running .msg-status { color: #b8860b; }
.msg-time { margin-left: auto; font-size: 12px; color: var(--text-2); }
.msg-summary { font-size: 13px; font-weight: 600; color: var(--text); }
.msg-detail { font-size: 12px; color: var(--text-2); margin-top: 2px; }
.msg-src { font-size: 12px; color: var(--text-2); margin-top: 2px; }
.drop-enter-active, .drop-leave-active { transition: all 0.18s; }
.drop-enter-from, .drop-leave-to { opacity: 0; transform: translateY(-6px); }

/* ---- 任务结果 toast（全站） ---- */
.toast {
  position: fixed; top: 76px; right: 20px; z-index: 999;
  background: #fff;
  border: 1px solid var(--border);
  border-left: 4px solid var(--primary);
  border-radius: 12px;
  padding: 12px 16px;
  min-width: 280px; max-width: 380px;
  box-shadow: 0 10px 30px rgba(60, 40, 20, 0.18);
}
.toast.done { border-left-color: #0a7d3a; }
.toast.failed { border-left-color: #e23; }
.toast-head { display: flex; align-items: center; justify-content: space-between; gap: 12px; }
.toast-title { font-weight: 800; font-size: 14px; }
.toast.done .toast-title { color: #0a7d3a; }
.toast.failed .toast-title { color: #e23; }
.toast-close { border: none; background: none; font-size: 18px; color: var(--text-2); cursor: pointer; line-height: 1; }
.toast-close:hover { color: var(--text); }
.toast-text { font-size: 13px; font-weight: 600; margin-top: 4px; }
.toast-detail { font-size: 12px; color: var(--text-2); margin-top: 2px; }
.toast-enter-active, .toast-leave-active { transition: all 0.25s; }
.toast-enter-from, .toast-leave-to { opacity: 0; transform: translateX(20px); }

@media (max-width: 860px) {
  .nav-links, .search-box { display: none; }
  .menu-btn { display: block; }
  .mobile-menu { display: flex; }
}
</style>
