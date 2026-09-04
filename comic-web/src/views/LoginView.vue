<script setup lang="ts">
import { ref } from 'vue'
import { useRouter } from 'vue-router'
import { login, register, setAuth } from '../api'

const router = useRouter()
const mode = ref<'login' | 'register'>('login')
const username = ref('')
const password = ref('')
const nickname = ref('')
const error = ref('')
const loading = ref(false)

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
    const res =
      mode.value === 'login'
        ? await login(username.value.trim(), password.value)
        : await register(username.value.trim(), password.value, nickname.value.trim())
    setAuth(res)
    router.push('/me')
  } catch (e: unknown) {
    error.value = e instanceof Error ? e.message : '操作失败，请重试'
  } finally {
    loading.value = false
  }
}

function onBack() {
  router.back()
}
</script>

<template>
  <div class="auth-wrap">
    <button class="back" @click="onBack">← 返回</button>
    <div class="auth-card">
      <div class="brand">
        <span class="brand-mark">漫</span>
        <span class="brand-text">漫阅<em>COMIC</em></span>
      </div>
      <h1 class="title">{{ mode === 'login' ? '登录' : '注册' }}</h1>
      <p class="sub">{{ mode === 'login' ? '登录后可同步收藏到云端' : '创建账号，收藏多端同步' }}</p>

      <form @submit.prevent="submit">
        <label class="field">
          <span>用户名</span>
          <input v-model="username" type="text" autocomplete="username" placeholder="3-32 个字符" />
        </label>

        <label v-if="mode === 'register'" class="field">
          <span>昵称（选填）</span>
          <input v-model="nickname" type="text" placeholder="展示名称" />
        </label>

        <label class="field">
          <span>密码</span>
          <input v-model="password" type="password" autocomplete="current-password" placeholder="至少 6 位" />
        </label>

        <p v-if="error" class="error">{{ error }}</p>

        <button class="btn block" type="submit" :disabled="loading">
          {{ loading ? '处理中…' : mode === 'login' ? '登录' : '注册' }}
        </button>
      </form>

      <button class="switch" @click="mode = mode === 'login' ? 'register' : 'login'">
        {{ mode === 'login' ? '没有账号？去注册' : '已有账号？去登录' }}
      </button>
    </div>

    <p class="hint">最近阅读无需登录即可使用 · 收藏需要登录以跨设备同步</p>
  </div>
</template>

<style scoped>
.auth-wrap {
  max-width: 420px;
  margin: 0 auto;
  padding: 20px 0 48px;
  position: relative;
}
.back {
  position: absolute;
  top: 4px;
  left: 0;
  border: none;
  background: none;
  color: var(--text-2);
  cursor: pointer;
  font-size: 14px;
  padding: 4px 0;
}
.back:hover { color: var(--primary); }

.auth-card {
  background: #fff;
  border-radius: 16px;
  padding: 32px 30px;
  box-shadow: var(--shadow-hover);
  text-align: center;
}
.brand { display: flex; align-items: center; justify-content: center; gap: 8px; margin-bottom: 8px; }
.brand-mark {
  width: 38px; height: 38px; border-radius: 10px;
  background: linear-gradient(135deg, var(--primary), var(--accent));
  color: #fff; font-weight: 800; font-size: 21px;
  display: flex; align-items: center; justify-content: center;
}
.brand-text { font-weight: 800; font-size: 20px; }
.brand-text em { font-style: normal; font-size: 12px; color: var(--primary); margin-left: 4px; letter-spacing: 1px; }

.title { margin: 14px 0 4px; font-size: 24px; }
.sub { margin: 0 0 22px; color: var(--text-2); font-size: 14px; }

.field { display: block; text-align: left; margin-bottom: 14px; }
.field span { display: block; font-size: 13px; color: var(--text-2); margin-bottom: 6px; font-weight: 600; }
.field input {
  width: 100%;
  border: 1px solid var(--border);
  border-radius: 10px;
  padding: 11px 14px;
  font-size: 15px;
  background: var(--bg);
  transition: border 0.15s, background 0.15s;
  color: var(--text);
}
.field input:focus { outline: none; border-color: var(--primary); background: #fff; }

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
