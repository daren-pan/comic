<script setup lang="ts">
// 全站布局（由 comic-web 的 App.vue 移植）：顶栏导航 + 消息中心 + 任务 toast。
//
// 与 App.vue 的差异：
//   - `<RouterView />` → `<slot />`（uni 无全局 outlet，改由每个页面用 <Layout> 包住自身内容）；
//   - `useRoute/useRouter` 来自 utils/router（compat 层，签名与 vue-router 同形）；
//   - `<RouterLink>` → `<view class="u-a" @click>`：`<a>` 在本项目里是**布局容器**
//     （.nav-links 的 flex 子项 / .mobile-menu 自己就是 display:flex），而小程序规定
//     `<text>` 内不得放 `<view>`/`<image>` 等块级组件，故统一映射成 `view` + `u-a` 类。
//
// ⚠️ **本端只保留移动形态**（2026-09-23）：comic-front 是移动端专用前端，网页端由 comic-web 承担。
//    因此桌面专属元素（logo / 顶栏主导航 / 用户胶囊 / 退出 / 登录链接 / 消息下拉浮层 / 页脚）
//    **已整体删除**，原来的 `@media (max-width: 860px)` 移动规则**提升为基础态**。
//    只有 ≤560px 那档保留（手机内部收紧间距 / 字号，不是桌面规则）。
import { ref, computed, onMounted, onBeforeUnmount, watch } from 'vue'
import { storeToRefs } from 'pinia'
import { useRoute, useRouter } from '../utils/router'
import { useUserStore } from '../stores/user'
import { kindLabel, statusLabel, useMessageStore } from '../stores/message'
import { TAB_ICONS, TAB_ICONS_DARK } from '../utils/icons'
import { useTheme } from '../utils/theme'

const route = useRoute()
const router = useRouter()

// 主题：模板根 `.app-shell` 挂 `.theme-dark`，整棵子树的 CSS 变量随之切换
const { isDark, toggleTheme } = useTheme()

const keyword = ref('')
const showMenu = ref(false)      // 菜单是否挂载（v-if）
const menuClosing = ref(false)   // 是否正在播放「滑回左侧」的收起动画

// 登录态：全局唯一来源 = Pinia user store（登录/登出/401 后自动同步）
const userStore = useUserStore()
const { isLoggedIn, isAdmin, isSuperAdmin, user } = storeToRefs(userStore)

// 消息中心：采集/巡检/自愈任务结果 + 系统消息。
// 本端只有移动形态 → 铃铛恒为「跳独立消息页」（见 pages/messages/index.vue）。
const msgStore = useMessageStore()

// 铃铛的落点（已读时机由页面自己管，见 pages/messages/index.vue）
function goMessages() {
  closeMenu() // 与移动端菜单互斥
  router.push('/messages')
}

onMounted(() => {
  userStore.init() // 开始监听 api 层 'auth:changed' 事件，同步登录态
  msgStore.init()  // 载入持久化的历史消息
})

onBeforeUnmount(() => {
  if (menuTimer) { clearTimeout(menuTimer); menuTimer = null } // 收起动画的定时器不能留到组件销毁之后
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
// 左上角 ☰ 打开。菜单是 fixed 覆盖层、**不占文档流**，所以不会把下面的页面挤下去
// （旧实现是 .nav 里的普通块级元素，展开会把整页顶下去，已废弃）。
//
// 进场/收起都走 CSS 动画（从左侧滑出，见 <style> 里的 drawer-in / drawer-out）：
// 不用 `<transition>` 组件 —— **小程序不支持**，会被当成未知组件。
const MENU_ANIM_MS = 240 // 必须与 .mobile-menu / .menu-mask 的 animation-duration 一致
let menuTimer: ReturnType<typeof setTimeout> | null = null

function openMenu() {
  if (menuTimer) { clearTimeout(menuTimer); menuTimer = null } // 收起动画没播完又要打开 → 取消待卸载
  menuClosing.value = false
  showMenu.value = true
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

// 路由切换时收起移动端菜单（登录态已由 store 自动同步，无需再手动刷新）
watch(() => route.path, () => {
  closeMenu()
})
</script>

<template>
  <view class="app-shell" :class="{ 'theme-dark': isDark }">
    <view class="nav">
      <view class="container nav-inner">
        <view class="nav-right">
          <!-- 提交语义走 uni 的 form-type（不是 HTML 的 type="submit"，那在 uni 里不触发提交）；
               回车提交用 uni-input 的 confirm 事件补齐（uni-form 不是原生 form，没有隐式提交）。 -->
          <form class="search-box" @submit="onSearch">
            <input class="u-input" v-model="keyword" type="text" placeholder="搜索漫画 / 作者 / 标签" @confirm="onSearch" />
            <button class="u-button" form-type="submit" aria-label="搜索">🔍</button>
          </form>

          <!-- 消息中心：任务结果 + 系统消息。点铃铛进独立消息页（本端只有移动形态）。
               ⚠️ 窄屏消息入口**不做宽度判断**，见 <style> 里的说明。 -->
          <view class="msg-wrap">
            <button class="msg-btn u-button" @click.stop="goMessages" title="消息">
              <text class="msg-icon u-span">🔔</text>
              <text v-if="msgStore.unread" class="msg-badge u-span">{{ msgStore.unread > 99 ? '99+' : msgStore.unread }}</text>
            </button>
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

          <!-- 菜单按钮：左上角 ☰。本端只保留移动形态，故恒显示（不再是窄屏专属）。
               靠 flex order 排到顶栏最左。 -->
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

      <!-- 账号区：窄屏唯一的账号入口（顶栏的「登录 / 用户胶囊」在窄屏已隐藏）。
           登录态 = 头像 + 昵称（占满剩余宽度）+ 右侧窄胶囊「退出登录」，同一行；
           未登录时没有用户块，那个「登录」按钮靠 .wide 单独保持整条宽度。 -->
      <view class="mm-account">
        <template v-if="isLoggedIn">
          <view class="mm-user">
            <text class="mm-avatar u-span">{{ (user?.nickname || '我').slice(0, 1) }}</text>
            <text class="mm-name u-span">{{ user?.nickname || user?.username }}</text>
          </view>
          <button class="mm-login-btn u-button" @click="onLogout(); closeMenu()">退出登录</button>
        </template>
        <button v-else class="mm-login-btn wide u-button" @click="goFromMenu('/login')">登录</button>
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

    <!-- 移动端底栏导航：本端只保留移动形态，故恒显示。
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
  gap: 10px;
  height: 60px;
}
/* 顶栏只有「菜单 · 搜索 · 消息 · 主题」四件（移动形态）。
   原来的 .logo / .nav-links / .user-chip / .logout / .login-link 已随桌面端一并删除。 */

.nav-right { display: flex; align-items: center; gap: 8px; flex: 1; min-width: 0; }
/* 用 order 重排而非改 DOM 顺序：DOM 里顺序是「搜索 · 消息 · 主题 · 菜单」，
   靠 order 把 ☰ 顶到最左，与移动端观感一致。 */
.search-box { order: 2; display: flex; align-items: center; background: var(--bg); border: 1px solid var(--border); border-radius: 999px; padding: 0 4px 0 14px; height: 36px; flex: 1 1 0; min-width: 0; transition: border 0.15s; }
.search-box:focus-within { border-color: var(--primary); background: var(--card); }
/* min-width:0 让 .u-input 可以真正收缩（默认 auto 会按默认字符宽度撑住，把右侧按钮压扁）； */
.search-box .u-input { border: none; outline: none; background: transparent; flex: 1 1 auto; min-width: 0; font-size: 13px; color: var(--text); }
/* 按钮固定 28×28 不被压缩，圆形图标居中 —— 否则窄容器下会被 flex 压成扁椭圆 */
.search-box .u-button { border: none; background: var(--primary); color: #fff; width: 28px; height: 28px; flex: 0 0 28px; border-radius: 999px; cursor: pointer; font-size: 12px; display: inline-flex; align-items: center; justify-content: center; line-height: 1; padding: 0; }

/* 菜单按钮：恒显示（本端只保留移动形态），靠 order 排到顶栏最左 */
.menu-btn { display: inline-flex; align-items: center; justify-content: center; order: 1; flex-shrink: 0; border: none; background: none; font-size: 21px; line-height: 1; cursor: pointer; color: var(--text); padding: 0 2px; }
.menu-btn.on { color: var(--primary); }

/* ---- 移动端菜单：二级页面（全屏覆盖层）。
   ⚠️ 本端只保留移动形态 → 不再有「默认隐藏、窄屏打开」那套，`.menu-mask` / `.mobile-menu`
   的完整样式定义在文件末尾（无条件生效），这里只放内部元素的样式。 */
.mm-head { display: flex; align-items: center; justify-content: space-between; padding: 4px 2px 12px; border-bottom: 1px solid var(--border); }
.mm-brand { font-weight: 800; font-size: 18px; color: var(--text); }
.mm-brand-en { font-style: normal; font-size: 11px; color: var(--primary); margin-left: 4px; letter-spacing: 1px; }
.mm-close { border: none; background: none; font-size: 22px; line-height: 1; color: var(--text-2); cursor: pointer; padding: 0 6px; }
/* 账号区一行：头像 + 昵称（吃掉剩余宽度）+ 右侧「退出登录」窄胶囊。
   .mm-user 的 min-width:0 必须留着，否则长昵称会把按钮挤出抽屉（flex 项默认 min-width:auto）。 */
.mm-account { display: flex; align-items: center; gap: 10px; padding: 14px 2px; border-bottom: 1px solid var(--border); }
.mm-user { display: flex; align-items: center; gap: 10px; flex: 1 1 auto; min-width: 0; }
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
  flex: 0 0 auto;
  border: none;
  border-radius: 8px;
  background: var(--primary);
  color: #fff;
  font-size: 13px; font-weight: 600;
  cursor: pointer;
  padding: 7px 12px;
  white-space: nowrap;
}
/* 未登录时账号区只有一个按钮，让它照旧占满整条 */
.mm-login-btn.wide { flex: 1 1 auto; font-size: 14px; padding: 9px 0; }
.mm-login-btn:hover { background: var(--primary-dark); }
.mm-list { display: flex; flex-direction: column; padding: 8px 0 0; }
.mm-list .u-a { padding: 11px 8px; border-radius: 8px; font-weight: 600; color: var(--text-2); }
.mm-list .u-a.on { color: var(--primary); background: var(--primary-soft); }

/* ---- 消息中心 ---- */
.msg-wrap { position: relative; flex-shrink: 0; }
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
.theme-btn { flex-shrink: 0; order: 4; }
/* ⚠️ 本端只有移动形态 → 铃铛恒为「跳独立消息页」，**没有**下拉浮层那一套
   （原 .wide-only / .narrow-only 二选一、.msg-panel 浮层、.msg-mask 遮罩、
   以及只服务浮层的 .msg-head/.msg-item 等样式，已随桌面端一并删除）。
   消息条目的样式在 pages/messages/index.vue 里自带一份（scoped）。 */
.msg-wrap { order: 3; }
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

/* ---- 底栏导航（移动形态，恒显示） ---- */
/* 底栏本体：fixed 贴底，不占文档流。阅读器是 position:fixed + z-index 200 的全屏层，
   会盖住它（与顶栏 z-index 100 同一处理方式，故不需要额外排除逻辑）。 */
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

/* 给固定底栏清障：内容容器底部留出底栏高度，否则最后一排卡片会被压住。
   （原先是靠页脚自己的 padding-bottom 承担，页脚已随桌面端删除，故必须留在这里。）
   `.page` 只在本组件模板上用（见 style.css 的 .page / .container 注释），
   且 `.page[data-v-*]` 比全局 `.page` 多一个属性选择器，能稳定盖过它的 48px。
   84px = 底栏本体约 50px + 34px 余量。 */
.page { padding-bottom: 84px; }
.page { padding-bottom: calc(84px + env(safe-area-inset-bottom)); }

/* 移动端菜单的「滑出 / 滑回」关键帧。
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
</style>
