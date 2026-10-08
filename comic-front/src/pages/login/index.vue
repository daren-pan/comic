<script setup lang="ts">
import { ref } from 'vue'
import { useUserStore } from '../../stores/user'
import { onLoad } from '@dcloudio/uni-app'
import { setRoute, useRouter } from '../../utils/router'
import { getSeasonLogo } from '../../utils/season'
import Layout from '../../components/Layout.vue'

const router = useRouter()

// 品牌标识随季节切换（与首页顶栏、抽屉同一套资源）
const logo = getSeasonLogo()
const userStore = useUserStore()
const mode = ref<'login' | 'register'>('login')
const username = ref('')
const password = ref('')
const nickname = ref('')
const error = ref('')
const loading = ref(false)

/** 登录成功后回哪儿：默认「我的」；带了 `?redirect=` 就回那儿（见 `normalizeRedirect`） */
const redirectTo = ref('/me')

/**
 * 收敛 `?redirect=`：**只接受站内绝对路径**，其余一律回默认。
 *
 * 为什么必须校验：这个参数是"跳到登录页时带上的原路径"（守卫 / 401 / 消息页都会带），
 * 但它来自 URL —— 不做校验就等于开放重定向（诱导用户点一条
 * `…/login?redirect=https://evil.example` 的链接，登录后被带走）。
 * 规则：必须以 `/` 开头、不能是 `//`（协议相对）、不能含 `://` 或反斜杠。
 *
 * ⚠️ 要**解两次**：uni 的页面栈会把 query 再编码一次，取到的是 `%252Fmessages`
 * 这种形态（2026-10-06 实测），只解一次会得到 `%2Fmessages` 这种非法路径。
 */
function normalizeRedirect(raw: unknown): string {
  let value = String(raw ?? '').trim()
  if (!value) return '/me'
  for (let i = 0; i < 2 && /%[0-9a-f]{2}/i.test(value); i += 1) {
    try {
      value = decodeURIComponent(value)
    } catch {
      break          // 编码坏了就按现在的样子继续校验（会被下面的规则挡掉）
    }
  }
  if (!value.startsWith('/') || value.startsWith('//') || value.includes('://') || value.includes('\\')) {
    return '/me'
  }
  return value
}

async function submit() {
  if (!username.value.trim() || !password.value) {
    error.value = '请输入用户名和密码'
    return
  }
  if (mode.value === 'register' && password.value.length < 6) {
    error.value = '密码长度至少 6 位'
    return
  }
  error.value = ''
  loading.value = true
  try {
    if (mode.value === 'login') {
      await userStore.login(username.value.trim(), password.value)
    } else {
      await userStore.register(username.value.trim(), password.value, nickname.value.trim())
    }
    // replace（不是 push）：登录页不该留在返回栈里 —— 否则回退会退回登录页
    router.replace(redirectTo.value)
  } catch (e: unknown) {
    error.value = e instanceof Error ? e.message : '操作失败，请重试'
  } finally {
    loading.value = false
  }
}

/**
 * 切换「登录 / 注册」。
 * 必须**顺手清掉上一条报错** —— 否则"登录失败"的红字会留在注册表单下面，
 * 让人误以为是"注册失败"（2026-09-18 用户就被这个误导过）。
 */
function toggleMode() {
  mode.value = mode.value === 'login' ? 'register' : 'login'
  error.value = ''
}

function onBack() {
  router.back()
}
// uni 页面生命周期：登记该页对应的 web 路径（替代 vue-router 的路由状态）+ 记住"登录后回哪儿"
onLoad((options) => {
  setRoute('/login', options ?? {})
  redirectTo.value = normalizeRedirect(options?.redirect)
})

</script>

<template>
  <Layout>
    <view class="auth-wrap">
      <view class="auth-card">
        <button class="back u-button" @click="onBack">← 返回</button>
        <view class="brand">
          <image class="brand-icon" :src="logo.icon" mode="aspectFit" />
          <image class="brand-text" :src="logo.text" mode="aspectFit" />
        </view>
        <view class="title u-h1">{{ mode === 'login' ? '登录' : '注册' }}</view>
        <view class="sub u-p">{{ mode === 'login' ? '登录后可同步收藏到云端' : '创建账号，收藏多端同步' }}</view>

        <form @submit="submit">
          <view class="field u-label">
            <text class="u-span">用户名</text>
            <input class="u-input" v-model="username" type="text" autocomplete="username" placeholder="3-32 个字符" @confirm="submit" />
          </view>

          <view v-if="mode === 'register'" class="field u-label">
            <text class="u-span">昵称（选填）</text>
            <input class="u-input" v-model="nickname" type="text" placeholder="展示名称" @confirm="submit" />
          </view>

          <view class="field u-label">
            <text class="u-span">密码</text>
            <input class="u-input" v-model="password" type="password" autocomplete="current-password" placeholder="至少 6 位" @confirm="submit" />
          </view>

          <view v-if="error" class="error u-p">{{ error }}</view>

          <button class="btn block u-button" form-type="submit" :disabled="loading">
            {{ loading ? '处理中…' : mode === 'login' ? '登录' : '注册' }}
          </button>
        </form>

        <button class="switch u-button" @click="toggleMode">
          {{ mode === 'login' ? '没有账号？去注册' : '已有账号？去登录' }}
        </button>
      </view>

      <view class="hint u-p">最近阅读无需登录即可使用 · 收藏需要登录以跨设备同步</view>
    </view>
  </Layout>
</template>

<style scoped>
.auth-wrap {
  max-width: 420px;
  margin: 0 auto;
  padding: 20px 0 48px;
}
/* 卡片本身作定位锚点 —— 返回按钮现在在**卡片内部**（原来锚在 .auth-wrap 上、按钮挂在卡片外）。 */
.auth-card {
  position: relative;
  background: var(--card);
  border-radius: 16px;
  padding: 32px 30px;
  box-shadow: var(--shadow-hover);
  text-align: center;
}
/* 卡片内左上角的返回：绿色纯文字，绝对定位贴角，不参与卡片内容流。 */
.back {
  position: absolute;
  top: 14px;
  left: 16px;
  border: none;
  background: none;
  color: #15803d;          /* 绿色（白底对比度 5.0:1，AA 达标）；调色板无绿色变量，故就地取值 */
  cursor: pointer;
  font-size: 14px;
  padding: 4px 0;
}
.back:hover { color: #166534; }
.brand { display: flex; align-items: center; justify-content: center; gap: 8px; margin-bottom: 8px; }
.brand-icon { width: 38px; height: 38px; }
/* 字标是 2:1 横排图，图上下各留白约 20% —— 高度 43px 时字面高约 26px */
.brand-text { width: 86px; height: 43px; }

.title { margin: 14px 0 4px; font-size: 24px; }
.sub { margin: 0 0 22px; color: var(--text-2); font-size: 14px; }

.field { display: block; text-align: left; margin-bottom: 14px; }
.field .u-span { display: block; font-size: 13px; color: var(--text-2); margin-bottom: 6px; font-weight: 600; }
.field .u-input {
  width: 100%;
  border: 1px solid var(--border);
  border-radius: 10px;
  padding: 11px 14px;
  font-size: 15px;
  background: var(--bg);
  transition: border 0.15s, background 0.15s;
  color: var(--text);
}
.field .u-input:focus { outline: none; border-color: var(--primary); background: var(--card); }

.error { color: #e23; font-size: 13px; margin: -4px 0 10px; text-align: left; }

.btn.block { width: 100%; justify-content: center; padding: 12px; font-size: 15px; }

.switch {
  margin-top: 18px;
  border: none;
  background: none;
  color: var(--primary);
  cursor: pointer;
  font-size: 14px;
  font-weight: 600;
}
.switch:hover { text-decoration: underline; }

.hint { text-align: center; color: var(--text-2); font-size: 12px; margin-top: 18px; }
</style>
