<script setup lang="ts">
// 全站布局（由 comic-web 的 App.vue 移植）：顶栏导航 + 消息中心 + 页脚 + 任务 toast。
//
// 与 App.vue 的差异：
//   - `<RouterView />` → `<slot />`（uni 无全局 outlet，改由每个页面用 <Layout> 包住自身内容）；
//   - `useRoute/useRouter` 来自 utils/router（compat 层，签名与 vue-router 同形）；
//   - `document.addEventListener`（点击空白关面板）仅在 H5 存在 → 条件编译；
//   - `<RouterLink>` → `<view class="u-a" @click>`：`<a>` 在本项目里是**布局容器**
//     （.nav-links 的 flex 子项 / .mobile-menu 自己就是 display:flex），而小程序规定
//     `<text>` 内不得放 `<view>`/`<image>` 等块级组件，故统一映射成 `view` + `u-a` 类。
import { ref, computed, onMounted, onBeforeUnmount, watch } from 'vue'
import { storeToRefs } from 'pinia'
import { useRoute, useRouter } from '../utils/router'
import { backendAlive } from '../api'
import { useUserStore } from '../stores/user'
import { useMessageStore } from '../stores/message'
import type { NoticeItem, NoticeKind } from '../stores/message'
import { TAB_ICONS, TAB_ICONS_DARK } from '../utils/icons'
import { useTheme } from '../utils/theme'

const route = useRoute()
const router = useRouter()

// 主题：模板根 `.app-shell` 挂 `.theme-dark`，整棵子树的 CSS 变量随之切换
const { isDark, toggleTheme } = useTheme()

const keyword = ref('')
const showMenu = ref(false)      // 菜单是否挂载（v-if）
const menuClosing = ref(false)   // 是否正在播放「滑回左侧」的收起动画
const backend = ref<boolean | null>(null)

// 登录态：全局唯一来源 = Pinia user store（登录/登出/401 后自动同步）
const userStore = useUserStore()
const { isLoggedIn: logged, isAdmin, isSuperAdmin, user } = storeToRefs(userStore)

// 消息中心：采集/巡检/自愈任务结果 + 系统消息（顶栏入口，点击展开面板）
const msgStore = useMessageStore()
const showMsg = ref(false)

function toggleMsg() {
  showMsg.value = !showMsg.value
  if (showMsg.value) {
    closeMenu() // 与移动端菜单互斥：两层浮层叠在一起会互相盖住
    msgStore.markAllRead() // 展开即视为已读
  }
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
        : k === 'heal'
          ? '自愈'
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
  // #ifdef H5
  document.addEventListener('click', onDocClick)
  // #endif
  backend.value = await backendAlive()
})

onBeforeUnmount(() => {
  if (menuTimer) { clearTimeout(menuTimer); menuTimer = null } // 收起动画的定时器不能留到组件销毁之后
  // #ifdef H5
  document.removeEventListener('click', onDocClick)
  // #endif
})

function onSearch() {
  const k = keyword.value.trim()
  router.push({ path: '/search', query: k ? { keyword: k } : {} })
  keyword.value = ''
  closeMenu() // 走同一套收起动画（菜单没开时是空操作）
}

function onLogout() {
  userStore.logout() // clearAuth + 广播事件 → store 自动同步 → 顶栏复位
  router.push('/')
}

// ---- 移动端底栏 ----
// 底栏三个入口（顺序：首页 / 最近更新 / 分类）
const tabs = [
  { path: '/', label: '首页' },
  { path: '/latest', label: '最近更新' },
  { path: '/search', label: '分类' },
]
// 图标颜色是烘死在 SVG 里的（<image> 不认 currentColor），夜间必须换另一套 ——
// 默认态用的是 --text-2，夜间该值变亮，不换图标在深底上基本看不见。
const tabIcons = computed(() => (isDark.value ? TAB_ICONS_DARK : TAB_ICONS))
function tabIcon(path: string, on: boolean): string {
  const k = path === '/' ? 'home' : path === '/latest' ? 'latest' : 'category'
  return on ? tabIcons.value[k].on : tabIcons.value[k].off
}

// ---- 移动端菜单（二级页面）----
// 窄屏左上角 ☰ 打开。菜单是 fixed 覆盖层、**不占文档流**，所以不会把下面的页面挤下去
// （旧实现是 .nav 里的普通块级元素，展开会把整页顶下去，已废弃）。
// 断点与 <style> 里的媒体查询一致（860px）。
//
// 进场/收起都走 CSS 动画（从左侧滑出，见 <style> 里的 drawer-in / drawer-out）：
// 不用 `<transition>` 组件 —— **小程序不支持**，会被当成未知组件。
const MENU_ANIM_MS = 240 // 必须与 .mobile-menu / .menu-mask 的 animation-duration 一致
let menuTimer: ReturnType<typeof setTimeout> | null = null

function openMenu() {
  if (menuTimer) { clearTimeout(menuTimer); menuTimer = null } // 收起动画没播完又要打开 → 取消待卸载
  menuClosing.value = false
  showMenu.value = true
  showMsg.value = false // 与消息面板互斥
}
// 关闭分两步：先挂 .closing 播「滑回」，动画结束（定时器到点）再真正卸载。
// 直接卸载的话元素会瞬间消失，看着还是「弹没了」。
function closeMenu() {
  if (!showMenu.value || menuClosing.value) return // 未打开 / 已在收起中 → 幂等，避免重复计时
  menuClosing.value = true
  menuTimer = setTimeout(() => {
    showMenu.value = false
    menuClosing.value = false
    menuTimer = null
  }, MENU_ANIM_MS)
}
// 走菜单里的导航项：先播完「滑回」动画，再跳转。
// uni 的页间跳转是**页面级**的（每个页面各自持有自己的 Layout），push 的瞬间整个
// Layout 就被卸载，抽屉会跟着秒消失 —— 动画白做，观感又回到「弹没了」。故延后到
// 动画结束再 push（同一时刻重复点击时，只保留最后一次目标）。
let navTimer: ReturnType<typeof setTimeout> | null = null
function goFromMenu(path: string) {
  closeMenu()
  if (navTimer) clearTimeout(navTimer)
  navTimer = setTimeout(() => {
    navTimer = null
    router.push(path)
  }, MENU_ANIM_MS)
}

// 点顶栏用户胶囊进「我的」。该胶囊只在宽屏出现 —— 窄屏顶栏的账号入口
// （登录 / 用户身份 / 退出）统一收进移动端菜单，顶栏只留「菜单 · 搜索 · 消息」。
function onUserClick() {
  router.push('/me')
}

// 路由切换时收起移动端菜单与消息面板（登录态已由 store 自动同步，无需再手动刷新）
watch(() => route.path, () => {
  closeMenu()
  showMsg.value = false
})
</script>

<template>
  <view class="app-shell" :class="{ 'theme-dark': isDark }">
    <view class="nav">
      <view class="container nav-inner">
        <view class="logo u-a" @click="router.push('/')">
          <text class="logo-mark u-span">漫</text>
          <text class="logo-text u-span">漫阅<text class="u-em">COMIC</text></text>
        </view>

        <view class="nav-links">
          <view class="u-a" :class="{ on: route.path === '/' }" @click="router.push('/')">首页</view>
          <view class="u-a" :class="{ on: route.path === '/search' }" @click="router.push('/search')">分类</view>
          <view class="u-a" :class="{ on: route.path === '/latest' }" @click="router.push('/latest')">最近更新</view>
          <view class="u-a" :class="{ on: route.path === '/rank' }" @click="router.push('/rank')">排行</view>
          <view class="u-a" :class="{ on: route.path === '/me' }" @click="router.push('/me')">我的</view>
          <!-- 管理：管理员（含超管）可见；授权：**仅超管**（普通管理员没有授权权限） -->
          <view v-if="isAdmin" class="u-a" :class="{ on: route.path === '/admin' }" @click="router.push('/admin')">管理</view>
          <view v-if="isSuperAdmin" class="u-a" :class="{ on: route.path === '/admin/users' }" @click="router.push('/admin/users')">授权</view>
        </view>

        <view class="nav-right">
          <!-- 提交语义走 uni 的 form-type（不是 HTML 的 type="submit"，那在 uni 里不触发提交）；
               回车提交用 uni-input 的 confirm 事件补齐（uni-form 不是原生 form，没有隐式提交）。 -->
          <form class="search-box" @submit="onSearch">
            <input class="u-input" v-model="keyword" type="text" placeholder="搜索漫画 / 作者 / 标签" @confirm="onSearch" />
            <button class="u-button" form-type="submit" aria-label="搜索">🔍</button>
          </form>

          <!-- 消息中心：任务结果 + 系统消息（点击展开） -->
          <view class="msg-wrap">
            <button class="msg-btn u-button" :class="{ on: showMsg }" @click.stop="toggleMsg" title="消息">
              <text class="msg-icon u-span">🔔</text>
              <text v-if="msgStore.unread" class="msg-badge u-span">{{ msgStore.unread > 99 ? '99+' : msgStore.unread }}</text>
            </button>
            <!-- #ifndef H5 -->
            <!-- 小程序没有全局 document 点击（H5 用 document.addEventListener('click') 关面板）：
                 铺一层透明遮罩承接「点空白关闭」。z-index 低于面板(200)、高于顶栏(100)。 -->
            <view v-if="showMsg" class="msg-mask" @click="showMsg = false"></view>
            <!-- #endif -->
            <view v-if="showMsg" class="msg-panel" @click.stop>
              <view class="msg-head">
                <text class="msg-title u-span">消息</text>
                <view class="msg-actions">
                  <button v-if="msgStore.unread" class="msg-link u-button" @click="msgStore.markAllRead()">全部已读</button>
                  <button v-if="msgStore.notices.length" class="msg-link u-button" @click="msgStore.clear()">清空</button>
                </view>
              </view>
              <view v-if="!msgStore.notices.length" class="msg-empty">暂无消息</view>
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
          </view>

          <!-- 主题切换：明亮 ↔ 夜间（选择存本地，未选过时跟随系统，见 utils/theme.ts） -->
          <button
            class="theme-btn u-button"
            :class="{ on: isDark }"
            :title="isDark ? '切换到明亮模式' : '切换到夜间模式'"
            :aria-label="isDark ? '切换到明亮模式' : '切换到夜间模式'"
            @click="toggleTheme"
          >
            <text class="theme-icon u-span">{{ isDark ? '☀️' : '🌙' }}</text>
          </button>

          <template v-if="logged">
            <button class="user-chip u-button" @click="onUserClick" title="我的书架">
              <text class="avatar u-span">{{ (user?.nickname || '我').slice(0, 1) }}</text>
              <text class="chip-name u-span">{{ user?.nickname || user?.username }}</text>
            </button>
            <button class="logout u-button" @click="onLogout">退出</button>
          </template>
          <view v-else class="login-link u-a" @click="router.push('/login')">登录</view>
          <!-- 移动端菜单按钮：窄屏靠 flex order 排到顶栏最左（左上角），桌面端 display:none -->
          <button class="menu-btn u-button" :class="{ on: showMenu }" @click="openMenu" aria-label="菜单">☰</button>
        </view>
      </view>
    </view>

    <!-- 移动端菜单：二级页面（全屏覆盖层，不占文档流，因此不会把下面的页面挤下去）。
         刻意放在 .nav **之外**：.nav 有 z-index:100 会形成层叠上下文，子元素 z-index 再大
         也压不过外面的底栏（z-index:120）。 -->
    <view v-if="showMenu" class="menu-mask" :class="{ closing: menuClosing }" @click="closeMenu"></view>
    <view v-if="showMenu" class="mobile-menu" :class="{ closing: menuClosing }" @click.stop>
      <view class="mm-head">
        <text class="mm-brand u-span">漫阅 <text class="mm-brand-en u-span">COMIC</text></text>
        <button class="mm-close u-button" @click="closeMenu" aria-label="关闭菜单">×</button>
      </view>

      <!-- 账号区：窄屏唯一的账号入口（顶栏的「登录 / 用户胶囊」在窄屏已隐藏） -->
      <view class="mm-account">
        <template v-if="logged">
          <view class="mm-user">
            <text class="mm-avatar u-span">{{ (user?.nickname || '我').slice(0, 1) }}</text>
            <text class="mm-name u-span">{{ user?.nickname || user?.username }}</text>
          </view>
          <button class="mm-login-btn u-button" @click="onLogout(); closeMenu()">退出登录</button>
        </template>
        <button v-else class="mm-login-btn u-button" @click="goFromMenu('/login')">登录</button>
      </view>

      <view class="mm-list">
        <view class="u-a" :class="{ on: route.path === '/' }" @click="goFromMenu('/')">首页</view>
        <view class="u-a" :class="{ on: route.path === '/search' }" @click="goFromMenu('/search')">分类</view>
        <view class="u-a" :class="{ on: route.path === '/latest' }" @click="goFromMenu('/latest')">最近更新</view>
        <view class="u-a" :class="{ on: route.path === '/rank' }" @click="goFromMenu('/rank')">排行</view>
        <view class="u-a" :class="{ on: route.path === '/me' }" @click="goFromMenu('/me')">我的收藏与历史</view>
        <view v-if="isAdmin" class="u-a" :class="{ on: route.path === '/admin' }" @click="goFromMenu('/admin')">采集管理</view>
        <view v-if="isSuperAdmin" class="u-a" :class="{ on: route.path === '/admin/users' }" @click="goFromMenu('/admin/users')">授权管理</view>
      </view>
    </view>

    <view class="container page">
      <slot />
    </view>

    <view class="footer">
      <view class="container">
        <view class="u-p">漫阅 Comic — 漫画聚合阅读平台
          <text v-if="backend === true" class="src-tag real u-span">● 已连接采集服务（真实数据）</text>
          <text v-else class="src-tag u-span">● 演示模式（本地 mock 数据）</text>
        </view>
        <view class="tip u-p">仅收录已授权 / 开放版权 / 公共领域内容 · 尊重版权，支持正版</view>
      </view>
    </view>

    <!-- 移动端底栏导航：≤860px 显示，桌面端隐藏。
         阅读器是 position:fixed + z-index 200 的全屏层，会盖住它（与顶栏同一处理方式，无需额外排除）。 -->
    <view class="bottom-nav">
      <view
        v-for="t in tabs"
        :key="t.path"
        class="bn-item"
        :class="{ on: route.path === t.path }"
        @click="router.push(t.path)"
      >
        <image class="bn-icon" :src="tabIcon(t.path, route.path === t.path)" mode="aspectFit" />
        <text class="bn-text u-span">{{ t.label }}</text>
      </view>
    </view>

    <!-- 任务结果 toast：任务执行完毕提示（全站可见） -->
    <view v-if="msgStore.toast" class="toast" :class="msgStore.toast.status">
      <view class="toast-head">
        <text class="toast-title u-span">{{ kindLabel(msgStore.toast.kind) }} · {{ statusLabel(msgStore.toast) }}</text>
        <button class="toast-close u-button" @click="msgStore.dismissToast()">×</button>
      </view>
      <view class="toast-text">{{ msgStore.toast.summary }}</view>
      <view v-if="msgStore.toast.detail" class="toast-detail">{{ msgStore.toast.detail }}</view>
    </view>
  </view>
</template>

<style scoped>
/* 模板根：主题切换的挂载点（`.theme-dark` 一挂，整棵子树的 CSS 变量随之切换，见 utils/theme.ts）。
   ⚠️ 这里**不能写** position / z-index / transform / filter —— 任何一样都会形成层叠上下文或
   包含块，里面那两个 position:fixed 的抽屉/遮罩就压不过外面的底栏了（它们本就为此放在 .nav 之外）。
   min-height:100vh 是给小程序兜底：那边 page 元素背景不随主题变，靠这层铺满视口。
   .nav 的 sticky 以本层为包含块，而本层铺满整页，所以吸顶行为与加包裹前一致。 */
.app-shell {
  min-height: 100vh;
  background: var(--bg);
}

.nav {
  position: sticky;
  top: 0;
  z-index: 100;
  background: var(--card);
  border-bottom: 1px solid var(--border);
  box-shadow: var(--shadow);
}
.nav-inner {
  display: flex;
  align-items: center;
  gap: 24px;
  height: 60px;
}
.logo { display: flex; align-items: center; gap: 8px; flex-shrink: 0; text-decoration: none; }
.logo-mark {
  width: 34px; height: 34px;
  border-radius: 9px;
  background: linear-gradient(135deg, var(--primary), var(--accent));
  color: #fff;
  font-weight: 800;
  font-size: 19px;
  display: flex; align-items: center; justify-content: center;
}
.logo-text { font-weight: 800; font-size: 19px; color: var(--text); }
.logo-text .u-em { font-style: normal; font-size: 11px; color: var(--primary); margin-left: 4px; letter-spacing: 1px; }

.nav-links { display: flex; gap: 2px; flex: 1; min-width: 0; }
.nav-links .u-a {
  padding: 6px 10px;
  border-radius: 8px;
  font-weight: 600;
  color: var(--text-2);
  white-space: nowrap;
  flex-shrink: 0;
  transition: all 0.15s;
  text-decoration: none;
}
.nav-links .u-a:hover { color: var(--primary); background: var(--primary-soft); }
.nav-links .u-a.on { color: var(--primary); background: var(--primary-soft); }

.nav-right { display: flex; align-items: center; gap: 10px; }
.search-box { display: flex; align-items: center; background: var(--bg); border: 1px solid var(--border); border-radius: 999px; padding: 0 4px 0 14px; height: 36px; width: 220px; min-width: 150px; flex-shrink: 1; transition: border 0.15s; }
.search-box:focus-within { border-color: var(--primary); background: var(--card); }
/* min-width:0 让 .u-input 可以真正收缩（默认 auto 会按默认字符宽度撑住，把右侧按钮压扁）； */
.search-box .u-input { border: none; outline: none; background: transparent; flex: 1 1 auto; min-width: 0; font-size: 13px; color: var(--text); }
/* 按钮固定 28×28 不被压缩，圆形图标居中 —— 否则窄容器下会被 flex 压成扁椭圆 */
.search-box .u-button { border: none; background: var(--primary); color: #fff; width: 28px; height: 28px; flex: 0 0 28px; border-radius: 999px; cursor: pointer; font-size: 12px; display: inline-flex; align-items: center; justify-content: center; line-height: 1; padding: 0; }

.menu-btn { display: none; border: none; background: none; font-size: 21px; line-height: 1; cursor: pointer; color: var(--text); padding: 0 2px; }
.menu-btn.on { color: var(--primary); }

.user-chip {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  border: 1px solid var(--border);
  background: var(--card);
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
/* 昵称过长时省略号截断（原选择器 .u-span:last-child 指向的是头像圆点，指错了对象） */
.user-chip .chip-name { min-width: 0; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
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
  text-decoration: none;
}
.login-link:hover { background: var(--primary-dark); }

/* ---- 移动端菜单：二级页面。默认（桌面端）整体隐藏，窄屏由媒体查询打开 ---- */
.menu-mask { display: none; }
.mobile-menu { display: none; }
.mm-head { display: flex; align-items: center; justify-content: space-between; padding: 4px 2px 12px; border-bottom: 1px solid var(--border); }
.mm-brand { font-weight: 800; font-size: 18px; color: var(--text); }
.mm-brand-en { font-style: normal; font-size: 11px; color: var(--primary); margin-left: 4px; letter-spacing: 1px; }
.mm-close { border: none; background: none; font-size: 22px; line-height: 1; color: var(--text-2); cursor: pointer; padding: 0 6px; }
.mm-account { padding: 14px 2px; border-bottom: 1px solid var(--border); }
.mm-user { display: flex; align-items: center; gap: 10px; margin-bottom: 12px; }
.mm-avatar {
  width: 36px; height: 36px;
  border-radius: 50%;
  background: linear-gradient(135deg, var(--primary), var(--accent));
  color: #fff;
  font-size: 15px; font-weight: 800;
  display: flex; align-items: center; justify-content: center;
  flex-shrink: 0;
}
.mm-name { font-weight: 700; font-size: 15px; color: var(--text); min-width: 0; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.mm-login-btn {
  width: 100%;
  border: none;
  border-radius: 8px;
  background: var(--primary);
  color: #fff;
  font-size: 14px; font-weight: 600;
  cursor: pointer;
  padding: 9px 0;
}
.mm-login-btn:hover { background: var(--primary-dark); }
.mm-list { display: flex; flex-direction: column; padding: 8px 0 0; }
.mm-list .u-a { padding: 11px 8px; border-radius: 8px; font-weight: 600; color: var(--text-2); }
.mm-list .u-a.on { color: var(--primary); background: var(--primary-soft); }

.footer {
  border-top: 1px solid var(--border);
  background: var(--card);
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
/* 点空白关闭的遮罩：只在非 H5 端渲染（H5 走 onDocClick 的 document 监听）。
   类名在这里无条件声明 —— H5 端没有这个元素，规则不生效，无需再套条件编译。 */
.msg-mask { position: fixed; top: 0; right: 0; bottom: 0; left: 0; z-index: 150; }
/* 顶栏圆形图标按钮：消息铃铛与主题切换**共用同一外形**（要改就改这一处） */
.msg-btn, .theme-btn {
  position: relative;
  width: 36px; height: 36px;
  display: inline-flex; align-items: center; justify-content: center;
  border: 1px solid var(--border);
  background: var(--card);
  border-radius: 50%;
  cursor: pointer;
  transition: all 0.15s;
}
.msg-btn:hover, .msg-btn.on, .theme-btn:hover, .theme-btn.on { border-color: var(--primary); background: var(--primary-soft); }
.theme-btn { flex-shrink: 0; }
.theme-icon { font-size: 15px; line-height: 1; }
.msg-icon { font-size: 16px; line-height: 1; }
.msg-badge {
  position: absolute; top: -4px; right: -4px;
  min-width: 16px; height: 16px; padding: 0 4px;
  background: var(--primary); color: #fff;
  font-size: 10px; font-weight: 700; line-height: 16px;
  border-radius: 999px; text-align: center;
  box-shadow: 0 0 0 2px var(--card);
}
.msg-panel {
  position: absolute; top: 46px; right: 0;
  width: 340px; max-width: calc(100vw - 32px);
  max-height: 440px;
  background: var(--card);
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
.msg-item.heal .msg-kind { background: #fff4e5; color: #a15c00; }
.msg-item.system .msg-kind { background: var(--mute); color: var(--text-2); }
.msg-status { font-size: 12px; font-weight: 700; }
.msg-item .msg-status { color: var(--text-2); }
.msg-item.done .msg-status { color: #0a7d3a; }
.msg-item.failed .msg-status { color: #e23; }
.msg-item.running .msg-status { color: #b8860b; }
.msg-time { margin-left: auto; font-size: 12px; color: var(--text-2); }
.msg-summary { font-size: 13px; font-weight: 600; color: var(--text); }
.msg-detail { font-size: 12px; color: var(--text-2); margin-top: 2px; }
.msg-src { font-size: 12px; color: var(--text-2); margin-top: 2px; }
/* ⚠️ 不用 `<transition>`：**小程序不支持该组件**（会被当成未知组件，弹层不显示或报错）。
   改用 CSS 动画表达「出现」——原 enter 的位移/淡入效果保留，leave 的淡出省略
   （v-if 立刻移除即可，视觉上等同原来的快速收起）。 */
.msg-panel { animation: drop-in 0.18s ease; }
@keyframes drop-in {
  from { opacity: 0; transform: translateY(-6px); }
  to { opacity: 1; transform: none; }
}

/* ---- 任务结果 toast（全站） ---- */
.toast {
  position: fixed; top: 76px; right: 20px; z-index: 999;
  background: var(--card);
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
/* 同上：`<transition>` 在小程序不可用，用 CSS 动画替代「出现」 */
.toast { animation: toast-in 0.25s ease; }
@keyframes toast-in {
  from { opacity: 0; transform: translateX(20px); }
  to { opacity: 1; transform: none; }
}

/* ---- 移动端底栏导航（默认隐藏，≤860px 显示） ---- */
.bottom-nav { display: none; }

/* 移动端菜单的「滑出 / 滑回」关键帧。定义在媒体查询**之外**（安全稳妥），
   只在窄屏被 .mobile-menu / .menu-mask 引用。
   时长与脚本里的 MENU_ANIM_MS 保持一致 —— 改一处要改两处。 */
@keyframes drawer-in {
  from { transform: translateX(-100%); }
  to { transform: translateX(0); }
}
@keyframes drawer-out {
  from { transform: translateX(0); }
  to { transform: translateX(-100%); }
}
@keyframes mask-in {
  from { opacity: 0; }
  to { opacity: 1; }
}
@keyframes mask-out {
  from { opacity: 1; }
  to { opacity: 0; }
}

@media (max-width: 860px) {
  /* 顶栏精简为「菜单 · 搜索 · 消息」：logo / 主导航 / 账号（登录·用户胶囊·退出）
     全部让位 —— 主导航交给底栏，账号入口交给左上角菜单。 */
  .logo, .nav-links, .logout, .login-link, .user-chip { display: none; }
  .nav-inner { gap: 10px; }
  .nav-right { flex: 1; gap: 8px; min-width: 0; }
  /* 用 order 重排而非改 DOM 顺序 —— 桌面端布局因此完全不受影响 */
  .menu-btn { display: inline-flex; align-items: center; justify-content: center; order: 1; flex-shrink: 0; }
  .search-box { order: 2; flex: 1 1 0; width: auto; min-width: 0; }
  .msg-wrap { order: 3; }
  .theme-btn { order: 4; }

  /* ---- 移动端菜单：全屏覆盖层（二级页面）。fixed 定位，不占文档流 ----
     抽屉从屏幕**左侧滑出**（而不是原地淡入/弹出）：进场 translateX(-100%) → 0，
     收起再滑回 -100%，遮罩同步淡入淡出。
     ⚠️ 不用 `<transition>`：小程序不支持该组件；这里用 CSS 动画表达。 */
  .menu-mask {
    display: block;
    position: fixed;
    top: 0; right: 0; bottom: 0; left: 0;
    z-index: 180;
    background: rgba(24, 18, 12, 0.45);
    animation: mask-in 0.24s ease;
  }
  .menu-mask.closing { animation: mask-out 0.24s ease forwards; }
  .mobile-menu {
    display: flex;
    position: fixed;
    top: 0; bottom: 0; left: 0;
    z-index: 190;
    width: 76vw;
    max-width: 300px;
    flex-direction: column;
    background: var(--card);
    box-shadow: 2px 0 18px rgba(60, 40, 20, 0.16);
    padding: calc(14px + env(safe-area-inset-top)) 16px calc(20px + env(safe-area-inset-bottom));
    overflow-y: auto;
    /* forwards 让收起动画停在屏幕外，等定时器卸载时不会闪一下回到屏内 */
    animation: drawer-in 0.24s cubic-bezier(0.22, 0.61, 0.36, 1);
  }
  .mobile-menu.closing { animation: drawer-out 0.24s cubic-bezier(0.22, 0.61, 0.36, 1) forwards; }

  /* 底栏本体 */
  .bottom-nav {
    display: flex;
    position: fixed;
    left: 0; right: 0; bottom: 0;
    z-index: 120;
    background: var(--card);
    border-top: 1px solid var(--border);
    box-shadow: 0 -2px 12px rgba(60, 40, 20, 0.06);
    padding-bottom: env(safe-area-inset-bottom); /* iPhone 底部安全区 */
  }
  .bn-item {
    flex: 1 1 0;
    display: flex; flex-direction: column; align-items: center; justify-content: center;
    gap: 3px;
    padding: 7px 0 6px;
    color: var(--text-2);
    cursor: pointer;
    transition: color 0.15s;
  }
  .bn-item.on { color: var(--primary); }
  .bn-icon { width: 22px; height: 22px; display: block; }
  .bn-text { font-size: 11px; line-height: 1; }

  /* 给页脚留出底栏高度，避免最后一行被固定底栏盖住。
     写两条：env() 不被支持时第二条整条作废，回落第一条。 */
  .footer { padding-bottom: 84px; }
  .footer { padding-bottom: calc(84px + env(safe-area-inset-bottom)); }
}
</style>
