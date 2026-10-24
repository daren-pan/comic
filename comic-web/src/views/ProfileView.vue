<script setup lang="ts">
// 个人中心（/profile，2026-10-12 新增）：列表式资料展示 + 编辑。
// - 可编辑：头像（上传 / 恢复默认）、昵称；另有「修改密码」与「退出登录」。
// - 只读：用户名 / 角色 / 注册时间。
// - 入口：抽屉账号行 / 抽屉菜单「个人中心」/ 网页版用户胶囊（见 components/Layout.vue）。
import { computed, onMounted, onUnmounted, ref } from 'vue'
import { storeToRefs } from 'pinia'
import {
  bindEmail,
  changePassword,
  clearAuth,
  fetchEmail,
  resetAvatar,
  sendBindCode,
  setUser,
  updateProfile,
  uploadAvatar,
} from '../api'
import { useUserStore } from '../stores/user'
import { useRouter } from 'vue-router'
import { hideLoading, showConfirm, showLoading, showToast } from '../utils/ui'
import Layout from '../components/Layout.vue'
import UserAvatar from '../components/UserAvatar.vue'

const router = useRouter()
const userStore = useUserStore()
const { isLoggedIn: logged, user } = storeToRefs(userStore)

// 角色徽章：只给管理员以上显示（普通用户不挂徽章）。口径与授权页一致。
const ROLE_LABELS: Record<string, string> = { superadmin: '超级管理员', admin: '普通管理员' }
const roleLabel = computed(() => (user.value ? (ROLE_LABELS[user.value.role] ?? '') : ''))

/** 注册时间 → 「2026-09-18」（createdAt 是 ISO 串，取日期部分） */
function joinDate(iso?: string): string {
  return iso ? iso.slice(0, 10) : ''
}

// ---- 弹层状态 ----
const avatarMenu = ref(false)    // 头像操作菜单（底部弹层）
const nicknameOpen = ref(false)  // 昵称编辑弹层
const pwdOpen = ref(false)       // 修改密码弹层
const emailOpen = ref(false)     // 绑定 / 更换邮箱弹层（2026-10-24）
const nickInput = ref('')
const oldPwd = ref('')
const newPwd = ref('')
const newPwd2 = ref('')
const busy = ref(false)          // 提交中（防重复点击）

// ---- 邮箱（2026-10-24：找回密码的通道）----
/** 已绑定邮箱的**脱敏**值（`ab***@qq.com`，由后端给）；空串 = 未绑定 */
const boundEmail = ref('')
const newEmail = ref('')
const emailCode = ref('')
/** 发码冷却剩余秒数（0 = 可点） */
const emailCountdown = ref(0)
let emailTimer: ReturnType<typeof setInterval> | undefined

function stopEmailTimer() {
  if (emailTimer) clearInterval(emailTimer)
  emailTimer = undefined
}
// 离开页面停掉定时器，否则每进一次页面多一个永不结束的 interval
onUnmounted(stopEmailTimer)

async function loadEmail() {
  try {
    const data = await fetchEmail()
    boundEmail.value = data.bound ? data.email : ''
  } catch {
    // 401 已由请求层统一处理（清登录态 + 跳登录页），这里不额外打扰用户
  }
}

function openEmail() {
  newEmail.value = ''
  emailCode.value = ''
  emailCountdown.value = 0
  stopEmailTimer()
  emailOpen.value = true
}

async function sendEmailCode() {
  const v = newEmail.value.trim()
  if (!v) {
    toast('请输入邮箱')
    return
  }
  if (busy.value) return
  busy.value = true
  try {
    const data = await sendBindCode(v)
    const seconds = Math.max(1, Math.floor(data?.cooldownSeconds || 60))
    emailCountdown.value = seconds
    stopEmailTimer()
    emailTimer = setInterval(() => {
      emailCountdown.value -= 1
      if (emailCountdown.value <= 0) stopEmailTimer()
    }, 1000)
    toast('验证码已发送，10 分钟内有效')
  } catch (e) {
    toast((e as Error).message)   // 含 409「该邮箱已被其他账号绑定」/ 429 频控
  } finally {
    busy.value = false
  }
}

async function saveEmail() {
  const v = newEmail.value.trim()
  if (!v) {
    toast('请输入邮箱')
    return
  }
  if (!/^\d{6}$/.test(emailCode.value.trim())) {
    toast('请输入 6 位验证码')
    return
  }
  if (busy.value) return
  busy.value = true
  try {
    const data = await bindEmail(v, emailCode.value.trim())
    boundEmail.value = data.email
    emailOpen.value = false
    stopEmailTimer()
    toast('邮箱已绑定')
  } catch (e) {
    toast((e as Error).message)
  } finally {
    busy.value = false
  }
}

function toast(title: string) {
  showToast(title)
}

// ---- 头像 ----
function pickAvatar() {
  avatarMenu.value = false
  // 纯 Web 的「选图」：动态起一个隐藏的 file input（accept 与后端校验一致）
  const input = document.createElement('input')
  input.type = 'file'
  input.accept = 'image/jpeg,image/png,image/webp,image/gif'
  input.onchange = async () => {
    const file = input.files?.[0]
    if (!file || busy.value) return
    busy.value = true
    showLoading('上传中…')
    // ⚠️ toast 要等 hideLoading 之后再弹：两个提示层叠着会互相盖住
    let err = ''
    try {
      setUser(await uploadAvatar(file))
    } catch (e) {
      err = (e as Error).message
    } finally {
      busy.value = false
      hideLoading()
    }
    toast(err || '头像已更新')
  }
  input.click()
}

async function doResetAvatar() {
  avatarMenu.value = false
  if (busy.value) return
  busy.value = true
  try {
    setUser(await resetAvatar())
    toast('已恢复默认头像')
  } catch (e) {
    toast((e as Error).message)
  } finally {
    busy.value = false
  }
}

// ---- 昵称 ----
function openNickname() {
  nickInput.value = user.value?.nickname || ''
  nicknameOpen.value = true
}

async function saveNickname() {
  const v = nickInput.value.trim()
  if (!v) {
    toast('昵称不能为空')
    return
  }
  if (v === (user.value?.nickname || '')) {
    nicknameOpen.value = false
    return
  }
  if (busy.value) return
  busy.value = true
  try {
    setUser(await updateProfile(v))
    nicknameOpen.value = false
    toast('昵称已更新')
  } catch (e) {
    toast((e as Error).message)
  } finally {
    busy.value = false
  }
}

// ---- 密码 ----
function openPassword() {
  oldPwd.value = ''
  newPwd.value = ''
  newPwd2.value = ''
  pwdOpen.value = true
}

async function savePassword() {
  if (!oldPwd.value || !newPwd.value || !newPwd2.value) {
    toast('请把三项都填完整')
    return
  }
  if (newPwd.value.length < 6) {
    toast('新密码至少 6 位')
    return
  }
  if (newPwd.value !== newPwd2.value) {
    toast('两次输入的新密码不一致')
    return
  }
  if (busy.value) return
  busy.value = true
  try {
    await changePassword(oldPwd.value, newPwd.value)
    pwdOpen.value = false
    // ⚠️ 改密会刷新 `user.password_changed_at` → **当前 token 立即失效**（后端全站生效）。
    // 不主动登出的话，用户接下来任何请求都会莫名 401（表现为"点了没反应再被踢走"）。
    clearAuth()
    toast('密码已更新，请重新登录')
    router.replace('/login')
  } catch (e) {
    toast((e as Error).message)
  } finally {
    busy.value = false
  }
}

// ---- 退出登录（二次确认）----
async function onLogout() {
  if (!(await showConfirm('确定要退出当前账号吗？', '退出登录'))) return
  userStore.logout()
  router.push('/')
}

onMounted(() => {
  // 拉一次最新资料：本地缓存的 user 可能没有 avatarUrl（该字段 2026-10-12 才加）
  if (logged.value) void userStore.refresh().catch(() => {})
  // 邮箱是脱敏值、且不在 UserOut 里（`/api/auth/me` 不带它）→ 单独取一次
  if (logged.value) void loadEmail()
})
// uni 页面生命周期：登记该页对应的 web 路径（替代 vue-router 的路由状态）
</script>

<template>
  <Layout>
    <div>
      <div class="section-title">个人中心</div>

      <!-- 未登录：引导 -->
      <div v-if="!logged" class="login-tip">
        <div class="u-p">登录后可修改资料、跨设备同步收藏与阅读进度</div>
        <button class="btn u-button" @click="router.push('/login')">去登录</button>
      </div>

      <template v-else>
        <!-- 资料列表：头像 / 昵称可点编辑；用户名 / 角色 / 注册时间只读 -->
        <div class="card">
          <div class="row" @click="avatarMenu = true">
            <span class="row-label u-span">头像</span>
            <div class="row-right">
              <UserAvatar :url="user?.avatarUrl" :name="user?.nickname || user?.username" :size="26" />
              <span class="chev u-span">›</span>
            </div>
          </div>
          <div class="row" @click="openNickname">
            <span class="row-label u-span">昵称</span>
            <div class="row-right">
              <span class="row-value u-span">{{ user?.nickname || user?.username }}</span>
              <span class="chev u-span">›</span>
            </div>
          </div>
          <div class="row">
            <span class="row-label u-span">用户名</span>
            <span class="row-value dim u-span">@{{ user?.username }}</span>
          </div>
          <div v-if="roleLabel" class="row">
            <span class="row-label u-span">角色</span>
            <span class="chip">{{ roleLabel }}</span>
          </div>
          <div class="row last">
            <span class="row-label u-span">注册时间</span>
            <span class="row-value dim u-span">{{ joinDate(user?.createdAt) }}</span>
          </div>
        </div>

        <!-- 邮箱（找回密码的通道）：未绑定 →「立即绑定」；已绑定 → 脱敏值 +「更换」 -->
        <div class="card">
          <div class="row last" @click="openEmail">
            <span class="row-label u-span">邮箱</span>
            <div class="row-right">
              <span v-if="boundEmail" class="row-value dim u-span">{{ boundEmail }}</span>
              <span v-else class="row-value u-span">未绑定</span>
              <span class="action u-span">{{ boundEmail ? '更换' : '立即绑定' }}</span>
              <span class="chev u-span">›</span>
            </div>
          </div>
        </div>

        <!-- 修改密码 -->
        <div class="card">
          <div class="row last" @click="openPassword">
            <span class="row-label u-span">修改密码</span>
            <span class="chev u-span">›</span>
          </div>
        </div>

        <!-- 退出登录 -->
        <div class="card logout-card">
          <div class="logout-btn u-a" @click="onLogout">退出登录</div>
        </div>
      </template>

      <!-- 头像操作（底部弹层） -->
      <div v-if="avatarMenu" class="mask" @click="avatarMenu = false"></div>
      <div v-if="avatarMenu" class="sheet">
        <div class="sheet-item u-a" @click="pickAvatar">选择新头像</div>
        <div v-if="user?.avatarUrl" class="sheet-item u-a" @click="doResetAvatar">恢复默认头像</div>
        <div class="sheet-item cancel u-a" @click="avatarMenu = false">取消</div>
      </div>

      <!-- 昵称编辑 -->
      <div v-if="nicknameOpen" class="mask" @click="nicknameOpen = false"></div>
      <div v-if="nicknameOpen" class="dialog">
        <div class="dlg-title">修改昵称</div>
        <input class="dlg-input" v-model="nickInput" :maxlength="64" placeholder="输入新昵称" @keyup.enter="saveNickname" />
        <div class="dlg-actions">
          <button class="btn ghost sm u-button" @click="nicknameOpen = false">取消</button>
          <button class="btn sm u-button" :disabled="busy" @click="saveNickname">保存</button>
        </div>
      </div>

      <!-- 修改密码 -->
      <div v-if="pwdOpen" class="mask" @click="pwdOpen = false"></div>
      <div v-if="pwdOpen" class="dialog">
        <div class="dlg-title">修改密码</div>
        <input class="dlg-input" v-model="oldPwd" type="password" placeholder="原密码" />
        <input class="dlg-input" v-model="newPwd" type="password" placeholder="新密码（6-128 位）" />
        <input class="dlg-input" v-model="newPwd2" type="password" placeholder="确认新密码" @keyup.enter="savePassword" />
        <div class="dlg-actions">
          <button class="btn ghost sm u-button" @click="pwdOpen = false">取消</button>
          <button class="btn sm u-button" :disabled="busy" @click="savePassword">保存</button>
        </div>
      </div>

      <!-- 绑定 / 更换邮箱（结构照上面对话框；验证码本身要校验，所以是「发码 → 填码 → 保存」三步） -->
      <div v-if="emailOpen" class="mask" @click="emailOpen = false"></div>
      <div v-if="emailOpen" class="dialog">
        <div class="dlg-title">{{ boundEmail ? '更换邮箱' : '绑定邮箱' }}</div>
        <input class="dlg-input" v-model="newEmail" type="email" placeholder="邮箱地址（找回密码用）" />
        <div class="dlg-code">
          <input
            class="dlg-input code"
            v-model="emailCode"
            type="text"
            inputmode="numeric"
            maxlength="6"
            placeholder="6 位验证码"
            @keyup.enter="saveEmail"
          />
          <button class="btn ghost sm u-button" :disabled="busy || emailCountdown > 0 || !newEmail" @click="sendEmailCode">
            {{ emailCountdown > 0 ? `${emailCountdown}s 后重发` : '获取验证码' }}
          </button>
        </div>
        <div class="dlg-tip u-p">验证码 10 分钟内有效；绑定后可用来找回密码</div>
        <div class="dlg-actions">
          <button class="btn ghost sm u-button" @click="emailOpen = false">取消</button>
          <button class="btn sm u-button" :disabled="busy" @click="saveEmail">保存</button>
        </div>
      </div>
    </div>
  </Layout>
</template>

<style scoped>
/* ---- 未登录引导 ---- */
.login-tip {
  text-align: center;
  background: var(--card);
  border: 1px solid var(--border);
  border-radius: var(--radius);
  padding: 48px 20px;
  color: var(--text-2);
}
.login-tip .u-p { margin: 0 0 16px; font-size: 14px; }

/* ---- 列表卡片 ---- */
.card {
  background: var(--card);
  border: 1px solid var(--border);
  border-radius: var(--radius);
  padding: 0 14px;
  margin-bottom: 12px;
}
.row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  padding: 12px 0;
  border-bottom: 1px solid var(--border);
  cursor: pointer;
}
.row.last { border-bottom: none; }
.row-label { font-size: 14px; color: var(--text); flex: none; }
.row-right { display: flex; align-items: center; gap: 6px; min-width: 0; }
.row-value { font-size: 13px; color: var(--text); min-width: 0; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.row-value.dim { color: var(--text-2); }
/* 行尾的操作词（「立即绑定」/「更换」）：绿色小字，与主链接同一套配色 */
.action { font-size: 13px; color: #15803d; flex: none; }
.chev { font-size: 16px; color: var(--text-2); line-height: 1; }

/* ---- 退出登录 ---- */
.logout-card { padding: 0; }
.logout-btn { text-align: center; padding: 13px 0; font-size: 14px; font-weight: 600; color: #e23; }

/* ---- 弹层（遮罩 / 底部菜单 / 居中对话框）---- */
.mask { position: fixed; top: 0; right: 0; bottom: 0; left: 0; z-index: 300; background: rgba(24, 18, 12, 0.45); }
.sheet {
  position: fixed; left: 0; right: 0; bottom: 0; z-index: 310;
  background: var(--card);
  border-radius: 16px 16px 0 0;
  padding: 4px 0 calc(6px + env(safe-area-inset-bottom));
}
.sheet-item { padding: 13px 16px; text-align: center; font-size: 15px; color: var(--text); border-bottom: 1px solid var(--border); }
.sheet-item.cancel { color: var(--text-2); border-bottom: none; }
.dialog {
  position: fixed; left: 50%; top: 42%; transform: translate(-50%, -50%); z-index: 310;
  width: 78vw; max-width: 340px;
  background: var(--card);
  border-radius: var(--radius);
  padding: 16px;
  box-shadow: var(--shadow-hover);
}
.dlg-title { font-size: 15px; font-weight: 700; color: var(--text); margin-bottom: 12px; }
.dlg-input {
  width: 100%;
  box-sizing: border-box;
  border: 1px solid var(--border);
  border-radius: 8px;
  padding: 8px 12px;
  font-size: 14px;
  color: var(--text);
  background: var(--bg);
  margin-bottom: 10px;
}
.dlg-input:focus { border-color: var(--primary); }
/* 验证码 +「获取验证码」同一行（倒计时期间按钮只是变灰） */
.dlg-code { display: flex; align-items: center; gap: 8px; }
.dlg-code .code { flex: 1; min-width: 0; margin-bottom: 0; }
.dlg-code .btn { flex: none; margin-bottom: 10px; white-space: nowrap; }
.dlg-tip { font-size: 12px; color: var(--text-2); margin: 8px 0 2px; line-height: 1.5; }
.dlg-actions { display: flex; justify-content: flex-end; gap: 8px; margin-top: 4px; }
.btn.sm { padding: 6px 14px; font-size: 13px; }
</style>
