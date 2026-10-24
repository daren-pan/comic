<script setup lang="ts">
// 忘记密码（/reset，2026-10-24 新增）：邮箱验证码 → 设新密码。**uni 版**，
// 与 comic-web 的 `views/ResetPasswordView.vue` 逐步对应、文案逐字一致（写法按本端约定）。
//
// 流程：
//   ① 填邮箱 →「获取验证码」→ 按钮进入 60 秒倒计时（disabled）→ 第 2 步展开
//   ② 6 位验证码 + 新密码 + 确认新密码 →「重置密码」
//   ③ 成功 → 提示「密码已重置」→ 1.5 秒后回登录页（重置会让旧 token 失效，只能重新登录）
//
// ⚠️ 后端发码接口对「已注册 / 未注册」邮箱返回完全一样的结果（反枚举），
// 所以不能拿响应当"邮箱存在"的证据，提示语照后端话术写「若该邮箱已注册…」。
import { onUnmounted, ref } from 'vue'
import { onLoad } from '@dcloudio/uni-app'
import { resetPassword, sendResetCode } from '../../api'
import { setRoute, useRouter } from '../../utils/router'
import { getSeasonLogo } from '../../utils/season'
import Layout from '../../components/Layout.vue'

const router = useRouter()
const logo = getSeasonLogo()

const email = ref('')
const code = ref('')
const newPassword = ref('')
const newPassword2 = ref('')
const error = ref('')
const notice = ref('')
const loading = ref(false)
/** 第 2 步是否已展开（拿到验证码之后才显示码 / 新密码表单） */
const expanded = ref(false)
/** 重置成功（与表单态互斥，避免重复提交） */
const done = ref(false)
/** 距离下次可重发还剩几秒（0 = 可点） */
const countdown = ref(0)

let timer: ReturnType<typeof setInterval> | undefined

/** 启动/重启动倒计时（秒数以后端返回的 `cooldownSeconds` 为准） */
function startCountdown(seconds: number) {
  countdown.value = Math.max(1, Math.floor(seconds || 60))
  if (timer) clearInterval(timer)
  timer = setInterval(() => {
    countdown.value -= 1
    if (countdown.value <= 0) {
      clearInterval(timer)
      timer = undefined
    }
  }, 1000)
}

// 离开页面必须停掉定时器：否则每进一次页面就多一个永不结束的 interval
onUnmounted(() => {
  if (timer) clearInterval(timer)
})

async function sendCode() {
  if (!email.value.trim()) {
    error.value = '请输入邮箱'
    return
  }
  error.value = ''
  loading.value = true
  try {
    const data = await sendResetCode(email.value.trim())
    expanded.value = true
    notice.value = '若该邮箱已注册，验证码已发送，10 分钟内有效'
    startCountdown(data?.cooldownSeconds ?? 60)
  } catch (e: unknown) {
    error.value = e instanceof Error ? e.message : '发送失败，请重试'
  } finally {
    loading.value = false
  }
}

async function submit() {
  if (!expanded.value) {
    await sendCode()
    return
  }
  if (!code.value.trim() || !newPassword.value || !newPassword2.value) {
    error.value = '请填写验证码与新密码'
    return
  }
  if (newPassword.value.length < 6) {
    error.value = '新密码长度至少 6 位'
    return
  }
  if (newPassword.value !== newPassword2.value) {
    error.value = '两次输入的新密码不一致'
    return
  }
  error.value = ''
  loading.value = true
  try {
    await resetPassword(email.value.trim(), code.value.trim(), newPassword.value)
    done.value = true
    notice.value = '密码已重置，请用新密码登录'
    // 重置会让此前签发的 token 全部失效 → 只有回登录页重新登录这条路是通的
    setTimeout(() => router.replace('/login'), 1500)
  } catch (e: unknown) {
    error.value = e instanceof Error ? e.message : '重置失败，请重试'
  } finally {
    loading.value = false
  }
}

function onBack() {
  router.replace('/login')
}

// uni 页面生命周期：登记该页对应的 web 路径（替代 vue-router 的路由状态）
onLoad((options) => setRoute('/reset', options ?? {}))
</script>

<template>
  <Layout>
    <view class="auth-wrap">
      <view class="auth-card">
        <button class="back u-button" @click="onBack">← 返回登录</button>
        <view class="brand">
          <image class="brand-icon" :src="logo.icon" mode="aspectFit" />
          <image class="brand-text" :src="logo.text" mode="aspectFit" />
        </view>
        <view class="title u-h1">找回密码</view>
        <view class="sub u-p">用绑定邮箱收取 6 位验证码，验证后即可设置新密码</view>

        <form @submit="submit">
          <view class="field u-label">
            <text class="u-span">邮箱</text>
            <view class="inline">
              <input
                class="u-input"
                v-model="email"
                type="text"
                autocomplete="email"
                placeholder="登录后在个人中心绑定的邮箱"
                :disabled="done"
                @confirm="sendCode"
              />
              <button
                class="btn ghost sm u-button"
                :disabled="loading || countdown > 0 || done"
                @click="sendCode"
              >
                {{ countdown > 0 ? `${countdown}s 后重发` : '获取验证码' }}
              </button>
            </view>
          </view>

          <template v-if="expanded && !done">
            <view class="field u-label">
              <text class="u-span">验证码</text>
              <input
                class="u-input"
                v-model="code"
                type="number"
                maxlength="6"
                placeholder="6 位数字，10 分钟内有效"
                @confirm="submit"
              />
            </view>

            <view class="field u-label">
              <text class="u-span">新密码</text>
              <input class="u-input" v-model="newPassword" password placeholder="6-128 位" @confirm="submit" />
            </view>

            <view class="field u-label">
              <text class="u-span">确认新密码</text>
              <input class="u-input" v-model="newPassword2" password placeholder="再输入一次新密码" @confirm="submit" />
            </view>
          </template>

          <view v-if="notice" class="notice u-p">{{ notice }}</view>
          <view v-if="error" class="error u-p">{{ error }}</view>

          <button v-if="!done" class="btn block u-button" form-type="submit" :disabled="loading">
            {{ loading ? '处理中…' : expanded ? '重置密码' : '获取验证码' }}
          </button>
        </form>

        <!-- 老用户（email 为 NULL）收不到码，是最容易被当 bug 反馈的情形 —— 这里固定说明怎么补 -->
        <view class="hint u-p">未绑定邮箱？请先登录，在「个人中心 → 邮箱」里绑定后再来</view>
      </view>
    </view>
  </Layout>
</template>

<style scoped>
.auth-wrap {
  max-width: 420px;
  margin: 0 auto;
  padding: 20px 0 48px;
}
.auth-card {
  position: relative;
  background: var(--card);
  border-radius: 16px;
  padding: 32px 30px;
  box-shadow: var(--shadow-hover);
  text-align: center;
}
.back {
  position: absolute;
  top: 14px;
  left: 16px;
  border: none;
  background: none;
  color: #15803d;
  cursor: pointer;
  font-size: 14px;
  padding: 4px 0;
}
.back:hover { color: #166534; }
.brand { display: flex; align-items: center; justify-content: center; gap: 8px; margin-bottom: 8px; }
.brand-icon { width: 38px; height: 38px; }
.brand-text { width: 86px; height: 43px; }

.title { margin: 14px 0 4px; font-size: 24px; }
.sub { margin: 0 0 22px; color: var(--text-2); font-size: 14px; }

.field { display: block; text-align: left; margin-bottom: 14px; }
.field .u-span { display: block; font-size: 13px; color: var(--text-2); margin-bottom: 6px; font-weight: 600; }
.field .u-input {
  width: 100%;
  box-sizing: border-box;
  border: 1px solid var(--border);
  border-radius: 10px;
  padding: 11px 14px;
  font-size: 15px;
  background: var(--bg);
  transition: border 0.15s, background 0.15s;
  color: var(--text);
}
.field .u-input:focus { outline: none; border-color: var(--primary); background: var(--card); }

/* 邮箱 +「获取验证码」同一行：倒计时期间按钮只是变灰，不占额外一行 */
.inline { display: flex; align-items: center; gap: 8px; }
.inline .u-input { flex: 1; min-width: 0; }
.btn.sm { padding: 10px 12px; font-size: 13px; white-space: nowrap; flex: none; }

.notice { color: #15803d; font-size: 13px; margin: -4px 0 10px; text-align: left; }
.error { color: #e23; font-size: 13px; margin: -4px 0 10px; text-align: left; }

.btn.block { width: 100%; justify-content: center; padding: 12px; font-size: 15px; }

.hint { text-align: center; color: var(--text-2); font-size: 12px; margin-top: 16px; line-height: 1.6; }
</style>
