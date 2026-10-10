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
// ⚠️ **两套形态**（2026-10-10 起）：**移动端为基准**（2026-09-23 定的形态，就是本文件
//    与各页 <style> 的主体规则），网页版是**新增的增量覆盖**（`.mode-web` 前缀，见文末
//    「网页版顶栏」段）。模式由 utils/layout.ts 管理（UA 判定默认 + 手动切换 + 本地记忆），
//    **仅 H5 有效** —— 小程序 / App 恒为移动版。
//    网页版专属元素（品牌 / 主导航 / 用户区 / 主题与布局切换键）用 `#ifdef H5` +
//    `v-if="isWebMode"` 双重守护：小程序构建时整块被条件编译剥掉，不留死代码。
import { ref, computed, onMounted, onBeforeUnmount, watch } from 'vue'
import { storeToRefs } from 'pinia'
import { useRoute, useRouter } from '../utils/router'
import { useUserStore } from '../stores/user'
import { kindLabel, statusLabel, useMessageStore } from '../stores/message'
import { TAB_ICONS, TAB_ICONS_DARK } from '../utils/icons'
import { useTheme } from '../utils/theme'
import { useLayoutMode } from '../utils/layout'
import { getSeasonLogo } from '../utils/season'

const route = useRoute()
const router = useRouter()

// 抽屉里的品牌标识随季节切换（与首页顶栏同一套资源）
const logo = getSeasonLogo()

// 顶栏「返回上一层」按钮的显隐：底栏那三个 tab 是**根页面**（没有上一层可回），
// 其余路由（/comic/:id 详情、/rank、/me、/messages、/admin*…）都是被 push 进来的二级页。
// ⚠️ 这份列表必须与下方 `tabs` 保持一致（同一个"根页面"概念，分两处写是历史原因）。
const ROOT_PATHS = ['/', '/latest', '/search']
const canGoBack = computed(() => !ROOT_PATHS.includes(route.path))

// 主题：模板根 `.app-shell` 挂 `.theme-dark`，整棵子树的 CSS 变量随之切换
// `setTheme` 供抽屉里的「背景主题」分段控件使用；`toggleTheme` 供**网页版顶栏**的主题
// 切换键使用（网页模式下抽屉不可达，那件设置项挪到顶栏）。
const { isDark, setTheme, toggleTheme } = useTheme()

// 布局模式（移动版 / 网页版，utils/layout.ts）。网页版顶栏放「切回移动版」键 ——
// 手机访问自动就是移动版，所以顶栏只需单向（网页 → 移动）；反方向在抽屉菜单里。
const { isWebMode, setMode } = useLayoutMode()

const keyword = ref('')
const showMenu = ref(false)      // 菜单是否挂载（v-if）
const menuClosing = ref(false)   // 是否正在播放「滑回右侧」的收起动画

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
})

// 消息中心：**面向所有登录用户**的通知中心（`message` 表，按角色/指定用户推送）。
// 数据源 `/api/messages` 只要登录（内容由服务端按当前账号的收件范围过滤），所以：
//   · 登录就拉起轮询、登出就停 —— 用 watch 而不是 onMounted 里判一次（登录态可能是
//     本机缓存、也可能要等 `/api/auth/me` 回来）；
//   · 管理员会多看到任务消息（`minRole='admin'`），普通用户只看到发给自己的。
watch(isLoggedIn, (ok) => (ok ? msgStore.start() : msgStore.stop()), { immediate: true })

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

// ---- 网页版主导航（2026-10-10）----
// 与底栏三 tab + 排行同一套入口（桌面习惯顺序：首页 / 分类 / 最近更新 / 排行）；
// 「管理 / 授权」两个入口按角色在模板里追加（与抽屉菜单同一套门槛）。
const NAV_LINKS = [
  { path: '/', label: '首页' },
  { path: '/search', label: '分类' },
  { path: '/latest', label: '最近更新' },
  { path: '/rank', label: '排行' },
]

// ---- 移动端菜单（二级页面）----
// 左上角 ☰ 打开。菜单是 fixed 覆盖层、**不占文档流**，所以不会把下面的页面挤下去
// （旧实现是 .nav 里的普通块级元素，展开会把整页顶下去，已废弃）。
//
// 进场/收起都走 CSS 动画（从**右侧**滑出，见 <style> 里的 drawer-in / drawer-out）：
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
        <!-- 网页版左区：品牌 + 主导航（`#ifdef H5` + v-if 双重守护 —— 小程序构建整块剥掉，
             移动版下不渲染）。样式见文末「网页版顶栏」段。 -->
        <!-- #ifdef H5 -->
        <template v-if="isWebMode">
          <view class="logo" @click="router.push('/')">
            <image class="logo-icon" :src="logo.icon" mode="aspectFit" />
            <image class="logo-text" :src="logo.text" mode="aspectFit" />
          </view>
          <view class="nav-links">
            <view
              v-for="l in NAV_LINKS"
              :key="l.path"
              class="nav-link u-a"
              :class="{ on: route.path === l.path }"
              @click="router.push(l.path)"
            >{{ l.label }}</view>
            <!-- 管理 / 授权：按角色显示（与抽屉菜单同一套门槛） -->
            <view v-if="isAdmin" class="nav-link u-a" :class="{ on: route.path === '/admin' }" @click="router.push('/admin')">管理</view>
            <view v-if="isSuperAdmin" class="nav-link u-a" :class="{ on: route.path === '/admin/users' }" @click="router.push('/admin/users')">授权</view>
          </view>
        </template>
        <!-- #endif -->

        <view class="nav-right">
          <!-- 提交语义走 uni 的 form-type（不是 HTML 的 type="submit"，那在 uni 里不触发提交）；
               回车提交用 uni-input 的 confirm 事件补齐（uni-form 不是原生 form，没有隐式提交）。 -->
          <form class="search-box" @submit="onSearch">
            <input class="u-input" v-model="keyword" type="text" placeholder="搜索漫画 / 作者 / 标签" @confirm="onSearch" />
            <button class="u-button" form-type="submit" aria-label="搜索">🔍</button>
          </form>

          <!-- 网页版：主题切换 + 布局切换（网页模式下抽屉不可达，这两件设置项放顶栏；
               布局键单向「网页 → 移动」，反方向在抽屉菜单里）。 -->
          <!-- #ifdef H5 -->
          <template v-if="isWebMode">
            <button class="icon-btn u-button" @click="toggleTheme()" :title="isDark ? '切换到明亮主题' : '切换到夜间主题'">{{ isDark ? '☀️' : '🌙' }}</button>
            <button class="icon-btn u-button" @click="setMode('mobile')" title="切换到移动版布局">📱</button>
          </template>
          <!-- #endif -->

          <!-- 消息中心：**面向所有登录用户**的通知（任务消息、维护公告、定向通知…）。
               两种形态都是「跳独立消息页」。
               ⚠️ 登录就显示：内容由服务端按"这条消息发给谁"过滤，普通用户看到的是发给自己的那些。
               ⚠️ 窄屏消息入口**不做宽度判断**，见 <style> 里的说明。 -->
          <view v-if="isLoggedIn" class="msg-wrap">
            <button class="msg-btn u-button" @click.stop="goMessages" title="消息">
              <text class="msg-icon u-span">🔔</text>
              <text v-if="msgStore.unread" class="msg-badge u-span">{{ msgStore.unread > 99 ? '99+' : msgStore.unread }}</text>
            </button>
          </view>

          <!-- 网页版右区：用户（登录 → 头像胶囊 + 退出；未登录 → 登录按钮）。
               胶囊点进「我的」；退出即 onLogout（清登录态 + 回首页）。 -->
          <!-- #ifdef H5 -->
          <template v-if="isWebMode">
            <template v-if="isLoggedIn">
              <view class="user-chip" @click="router.push('/me')">
                <text class="user-avatar u-span">{{ (user?.nickname || '我').slice(0, 1) }}</text>
                <text class="user-name u-span">{{ user?.nickname || user?.username }}</text>
              </view>
              <button class="logout-btn u-button" @click="onLogout">退出</button>
            </template>
            <button v-else class="login-link u-button" @click="router.push('/login')">登录</button>
          </template>
          <!-- #endif -->

          <!-- 移动版：返回上一层 + 菜单键 ☰（返回键网页版不渲染，由桌面导航替代；
               ☰ 在网页版**宽窗**由 CSS 隐藏，窄窗（≤860px）恢复显示 —— 桌面导航放不下时
               主导航收进抽屉）。
               返回键只在**非底栏 tab 页**显示（详情 / 排行 / 我的 / 消息 / 管理台…），
               `router.back()` 自带兜底（无历史时回首页），直接打开详情链接也不会卡住。
               图标 `❮`（U+276E 重角引号）：同方向但笔画比 `<` 粗、不显小（2026-10-07 用户反馈）。
               ⚠️ 两件都靠 flex order 排位（返回 0 / ☰ 5），别改 DOM 顺序。 -->
          <button
            v-if="!isWebMode && canGoBack"
            class="back-btn u-button"
            @click="router.back()"
            aria-label="返回上一层"
          >❮</button>
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
        <view class="mm-brand">
          <image class="mm-brand-icon" :src="logo.icon" mode="aspectFit" />
          <image class="mm-brand-text" :src="logo.text" mode="aspectFit" />
        </view>
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

      <!-- 背景主题：从顶栏移进抽屉（2026-10-07 用户要求）。选择存本地，
           未选过时跟随系统，见 utils/theme.ts。用分段控件而不是单个切换键 —— 当前态一眼可见。 -->
      <view class="mm-row">
        <text class="mm-row-label u-span">背景主题</text>
        <view class="mm-seg">
          <button class="mm-seg-btn u-button" :class="{ on: !isDark }" @click="setTheme('light')">☀️ 明亮</button>
          <button class="mm-seg-btn u-button" :class="{ on: isDark }" @click="setTheme('dark')">🌙 夜间</button>
        </view>
      </view>

      <!-- 页面布局：移动版 / 网页版（**仅 H5** —— 小程序 / App 恒为移动版，没有网页形态）。
           切到网页版后抽屉自动关掉：网页模式没有 ☰（顶栏换成桌面导航），
           切回移动版走网页版顶栏的 📱 键。选择存本地，见 utils/layout.ts。 -->
      <!-- #ifdef H5 -->
      <view class="mm-row">
        <text class="mm-row-label u-span">页面布局</text>
        <view class="mm-seg">
          <button class="mm-seg-btn u-button" :class="{ on: !isWebMode }" @click="setMode('mobile')">📱 移动版</button>
          <button class="mm-seg-btn u-button" :class="{ on: isWebMode }" @click="setMode('web'); closeMenu()">🖥 网页版</button>
        </view>
      </view>
      <!-- #endif -->

      <view class="mm-list">
        <view class="u-a" :class="{ on: route.path === '/' }" @click="goFromMenu('/')">首页</view>
        <view class="u-a" :class="{ on: route.path === '/search' }" @click="goFromMenu('/search')">分类</view>
        <view class="u-a" :class="{ on: route.path === '/latest' }" @click="goFromMenu('/latest')">最近更新</view>
        <view class="u-a" :class="{ on: route.path === '/rank' }" @click="goFromMenu('/rank')">排行</view>
        <view class="u-a" :class="{ on: route.path === '/me' }" @click="goFromMenu('/me')">我的收藏与历史</view>
        <view v-if="isAdmin" class="u-a" :class="{ on: route.path === '/admin' }" @click="goFromMenu('/admin')">采集管理</view>
        <!-- ⚠️ 「作品管理」不在菜单里 —— 它是管理台那一栏选项卡的第 2 个
             （见 components/AdminTabs.vue；与「定时任务」「运行日志」同一处理）。
             管理台的抽屉入口保持一个「采集管理」。 -->
        <view v-if="isSuperAdmin" class="u-a" :class="{ on: route.path === '/admin/users' }" @click="goFromMenu('/admin/users')">授权管理</view>
      </view>
    </view>

    <view class="container page">
      <slot />
    </view>

    <!-- 移动版底栏导航：只在移动版渲染（网页版导航在顶栏，整块不渲染）。
         阅读器是 position:fixed + z-index 200 的全屏层，会盖住它（与顶栏同一处理方式，无需额外排除）。 -->
    <view v-if="!isWebMode" class="bottom-nav">
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

    <!-- 任务结果 toast：任务执行完毕提示（全站可见）。内容来自服务端消息（见 stores/message.ts） -->
    <view v-if="msgStore.toast" class="toast" :class="msgStore.toast.status">
      <view class="toast-head">
        <text class="toast-title u-span">{{ kindLabel(msgStore.toast.kind) }} · {{ statusLabel(msgStore.toast) }}</text>
        <button class="toast-close u-button" @click="msgStore.dismissToast()">×</button>
      </view>
      <view class="toast-text">{{ msgStore.toast.title }}</view>
      <view v-if="msgStore.toast.body" class="toast-detail">{{ msgStore.toast.body }}</view>
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
/* 移动形态只有「搜索 · 消息 · 返回 · 菜单」四件；网页版另有品牌 / 主导航 / 用户区 /
   主题与布局键（2026-10-10 新增，样式见文末「网页版顶栏」段）。 */

.nav-right { display: flex; align-items: center; gap: 8px; flex: 1; min-width: 0; }
/* 用 order 重排而非改 DOM 顺序：DOM 里顺序是「搜索 · 消息 · 主题 · 菜单」，
   靠 order 把 ☰ 顶到最左，与移动端观感一致。 */
.search-box { order: 2; display: flex; align-items: center; background: var(--bg); border: 1px solid var(--border); border-radius: 999px; padding: 0 4px 0 14px; height: 36px; flex: 1 1 0; min-width: 0; transition: border 0.15s; }
.search-box:focus-within { border-color: var(--primary); background: var(--card); }
/* min-width:0 让 .u-input 可以真正收缩（默认 auto 会按默认字符宽度撑住，把右侧按钮压扁）； */
.search-box .u-input { border: none; outline: none; background: transparent; flex: 1 1 auto; min-width: 0; font-size: 13px; color: var(--text); }
/* 按钮固定 28×28 不被压缩，圆形图标居中 —— 否则窄容器下会被 flex 压成扁椭圆 */
.search-box .u-button { border: none; background: var(--primary); color: #fff; width: 28px; height: 28px; flex: 0 0 28px; border-radius: 999px; cursor: pointer; font-size: 12px; display: inline-flex; align-items: center; justify-content: center; line-height: 1; padding: 0; }

/* 返回上一层：只在二级页出现，靠 order 排到最前（顶栏最左）。
   字形用 ❮（重角引号）而不是 < —— 同样方向但笔画粗、视觉尺寸更大，不会显得又细又小；
   字号取 21px 与 ☰ 一致（❮ 自带较多边距，同字号下比 < 更小，所以不能沿用 19px）。 */
.back-btn { display: inline-flex; align-items: center; justify-content: center; order: 0; flex-shrink: 0; border: none; background: none; font-size: 21px; line-height: 1; cursor: pointer; color: var(--text); padding: 0 8px 0 0; }

/* 菜单按钮：移动版恒显示（网页版不渲染），靠 order 排到顶栏**最右**（铃铛之后） */
.menu-btn { display: inline-flex; align-items: center; justify-content: center; order: 5; flex-shrink: 0; border: none; background: none; font-size: 21px; line-height: 1; cursor: pointer; color: var(--text); padding: 0 2px; }
.menu-btn.on { color: var(--primary); }

/* ---- 移动端菜单：二级页面（全屏覆盖层）。
   ⚠️ 本端只保留移动形态 → 不再有「默认隐藏、窄屏打开」那套，`.menu-mask` / `.mobile-menu`
   的完整样式定义在文件末尾（无条件生效），这里只放内部元素的样式。 */
.mm-head { display: flex; align-items: center; justify-content: space-between; padding: 4px 2px 12px; border-bottom: 1px solid var(--border); }
.mm-brand { display: flex; align-items: center; gap: 8px; }
.mm-brand-icon { width: 28px; height: 28px; }
.mm-brand-text { width: 64px; height: 32px; }
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

/* 抽屉里的「背景主题」行（2026-10-07 从顶栏搬进来）：左侧标签 + 右侧分段控件 */
.mm-row { display: flex; align-items: center; justify-content: space-between; gap: 10px; padding: 12px 2px; border-bottom: 1px solid var(--border); }
.mm-row-label { font-size: 13px; font-weight: 600; color: var(--text-2); }
.mm-seg { display: flex; gap: 6px; }
.mm-seg-btn { border: 1px solid var(--border); background: var(--card); color: var(--text-2); font-size: 12px; line-height: 1.2; padding: 6px 12px; border-radius: 999px; cursor: pointer; white-space: nowrap; }
.mm-seg-btn.on { border-color: var(--primary); background: var(--primary); color: #fff; }
.mm-list { display: flex; flex-direction: column; padding: 8px 0 0; }.mm-list .u-a { padding: 11px 8px; border-radius: 8px; font-weight: 600; color: var(--text-2); }
.mm-list .u-a.on { color: var(--primary); background: var(--primary-soft); }

/* ---- 消息中心 ---- */
.msg-wrap { position: relative; flex-shrink: 0; }
/* 顶栏圆形图标按钮（消息铃铛；主题切换已于 2026-10-07 移进抽屉菜单） */
.msg-btn {
  position: relative;
  width: 36px; height: 36px;
  display: inline-flex; align-items: center; justify-content: center;
  border: 1px solid var(--border);
  background: var(--card);
  border-radius: 50%;
  cursor: pointer;
  transition: all 0.15s;
}
.msg-btn:hover, .msg-btn.on { border-color: var(--primary); background: var(--primary-soft); }
/* ⚠️ 两种形态的铃铛都是「跳独立消息页」，**没有**下拉浮层那一套
   （原 .wide-only / .narrow-only 二选一、.msg-panel 浮层、.msg-mask 遮罩、
   以及只服务浮层的 .msg-head/.msg-item 等样式，已随桌面端一并删除）。
   消息条目的样式在 pages/messages/index.vue 里自带一份（scoped）。 */
.msg-wrap { order: 3; }
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

/* ---- 底栏导航（仅移动版渲染；网页版整块不渲染） ---- */
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
  from { transform: translateX(100%); }
  to { transform: translateX(0); }
}
@keyframes drawer-out {
  from { transform: translateX(0); }
  to { transform: translateX(100%); }
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
   抽屉从屏幕**右侧滑出**（而不是原地淡入/弹出）：进场 translateX(100%) → 0，
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
  /* 2026-10-07 用户要求：抽屉改为**从右侧**移入移出（与 ☰ 挪到顶栏最右一致）。
     原先是 left: 0 + 向左的投影。 */
  top: 0; bottom: 0; right: 0;
  z-index: 190;
  width: 76vw;
  max-width: 300px;
  flex-direction: column;
  background: var(--card);
  /* 投影朝左（抽屉贴右边缘），原来是朝右的 2px */
  box-shadow: -2px 0 18px rgba(60, 40, 20, 0.16);
  padding: calc(14px + env(safe-area-inset-top)) 16px calc(20px + env(safe-area-inset-bottom));
  overflow-y: auto;
  /* forwards 让收起动画停在屏幕外，等定时器卸载时不会闪一下回到屏内 */
  animation: drawer-in 0.24s cubic-bezier(0.22, 0.61, 0.36, 1);
}
.mobile-menu.closing { animation: drawer-out 0.24s cubic-bezier(0.22, 0.61, 0.36, 1) forwards; }

/* 网页版样式只进 H5 产物（小程序 / App 恒为移动版、`.mode-web` 永不出现）——
   整段由条件编译包裹，mp 构建时剥掉、不留死 CSS（先例：App.vue 的 MP-WEIXIN 段）。
   ⚠️ 这段里**只放网页版规则**，别把移动端规则写进来。 */
/* #ifdef H5 */
/* ==================== 网页版顶栏（2026-10-10） ====================
   移动端为基准（上面全部规则），网页版是 `.mode-web` 前缀的**增量覆盖**。
   `.mode-web` 挂在 H5 的 <html> 上（见 utils/layout.ts），小程序 / App 不产生该前缀；
   元素的可见性由模板的 `#ifdef H5` + `v-if="isWebMode"` 控制，这里只管样式与排布。 */

/* 顶栏整体：略高一点、间距放宽 */
.mode-web .nav-inner { gap: 16px; height: 64px; }
/* 右组收成内容宽（移动版是 flex:1 占满整条）—— 左区主导航负责吃剩余空间 */
.mode-web .nav-right { flex: 0 0 auto; gap: 10px; }

/* 品牌（与抽屉头部同一套季节资源） */
.logo { display: flex; align-items: center; gap: 8px; cursor: pointer; flex-shrink: 0; }
.logo-icon { width: 30px; height: 30px; }
.logo-text { width: 70px; height: 34px; }

/* 主导航：吃掉左区剩余宽度 */
.nav-links { display: flex; align-items: center; gap: 2px; flex: 1 1 auto; min-width: 0; }
.nav-link {
  padding: 7px 12px;
  border-radius: 8px;
  font-size: 14px;
  font-weight: 600;
  color: var(--text-2);
  cursor: pointer;
  white-space: nowrap;
  transition: color 0.15s, background 0.15s;
}
.nav-link:hover { color: var(--text); background: var(--bg); }
.nav-link.on { color: var(--primary); background: var(--primary-soft); }

/* 网页版搜索框：收成固定宽度（移动版是 flex:1 撑满） */
.mode-web .search-box { flex: 0 1 240px; }

/* 圆形图标键（主题 / 布局切换）——与消息铃铛同款 */
.icon-btn {
  width: 36px; height: 36px;
  display: inline-flex; align-items: center; justify-content: center;
  border: 1px solid var(--border);
  background: var(--card);
  border-radius: 50%;
  cursor: pointer;
  font-size: 15px;
  line-height: 1;
  padding: 0;
  flex-shrink: 0;
  transition: border-color 0.15s, background 0.15s;
}
.icon-btn:hover { border-color: var(--primary); background: var(--primary-soft); }

/* 用户区：登录 → 头像胶囊（点进「我的」）+ 退出；未登录 → 登录按钮 */
.user-chip {
  display: flex; align-items: center; gap: 8px;
  padding: 3px 12px 3px 4px;
  border: 1px solid var(--border);
  border-radius: 999px;
  background: var(--card);
  cursor: pointer;
  flex-shrink: 0;
  transition: border-color 0.15s;
}
.user-chip:hover { border-color: var(--primary); }
.user-avatar {
  width: 28px; height: 28px;
  border-radius: 50%;
  background: linear-gradient(135deg, var(--primary), var(--accent));
  color: #fff;
  font-size: 13px; font-weight: 800;
  display: flex; align-items: center; justify-content: center;
  flex-shrink: 0;
}
.user-name { font-size: 13px; font-weight: 600; color: var(--text); max-width: 96px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.logout-btn { border: none; background: none; color: var(--text-2); font-size: 13px; font-weight: 600; cursor: pointer; padding: 6px 2px; white-space: nowrap; flex-shrink: 0; }
.logout-btn:hover { color: var(--primary); }
.login-link { border: none; background: var(--primary); color: #fff; font-size: 13px; font-weight: 600; padding: 7px 18px; border-radius: 999px; cursor: pointer; white-space: nowrap; flex-shrink: 0; }
.login-link:hover { background: var(--primary-dark); }

/* 网页版右组内部的排位（沿用 order 体系，不动 DOM 顺序）：
   搜索 2 → 主题/布局 3 → 铃铛 4 → 用户区 5 */
.mode-web .icon-btn { order: 3; }
.mode-web .msg-wrap { order: 4; }
.mode-web .user-chip, .mode-web .logout-btn, .mode-web .login-link { order: 5; }

/* 网页版**宽窗**：桌面导航完整 → 隐藏 ☰（窄窗由下方媒体查询恢复显示） */
.mode-web .menu-btn { display: none; }

/* 窄窗（≤860px）的网页版：桌面导航放不下 → 主导航收进抽屉、☰ 恢复显示；
   主题 / 布局 / 用户区也一并收（抽屉里有对应入口：背景主题 / 页面布局 / 账号区），
   顶栏只留「品牌 + 搜索 + 铃铛 + ☰」。
   ⚠️ 860 与各页的窄屏断点一致（管理台 / 详情页单栏化都在 860）。 */
@media (max-width: 860px) {
  .mode-web .nav-links,
  .mode-web .icon-btn,
  .mode-web .user-chip,
  .mode-web .logout-btn,
  .mode-web .login-link { display: none; }
  /* 右组恢复可收缩（宽窗的 `flex: 0 0 auto` 不收缩，窄窗会顶出横向滚动条 —— 实测 393px 溢出 50px） */
  .mode-web .nav-right { flex: 1 1 auto; min-width: 0; }
  .mode-web .search-box { flex: 1 1 auto; }
  .mode-web .menu-btn { display: inline-flex; }
}

/* 网页版内容底部不需要给底栏留白（底栏整块不渲染） */
.mode-web .page { padding-bottom: 48px; }
/* #endif */
</style>
