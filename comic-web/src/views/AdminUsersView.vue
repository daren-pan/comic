<script setup lang="ts">
// 授权页（/#/admin/users）—— **仅超级管理员**
//
// 职责：列出全部用户，在「普通管理员」与「普通用户」之间切换。
// 为什么需要它：管理台/日志要管理员角色，而**授权只有超管能做**（普通管理员进不来这一页）——
// 否则被授权的普通管理员反手就能把真正的超管降级（2026-09-18 实测到的漏洞）。
//
// 三档规则（前后端一致，后端在 services/accounts.py）：
// 1. 不能改自己 —— 唯一的超管把自己降级后再也没人能进授权页；
// 2. 不能授予超级管理员 —— 超管全库唯一，只能由"首个注册用户"或
//    `tools/add_user_role.py --superadmin <用户名>` 产生；
// 3. 不能改超级管理员的角色 —— 超管不可被任何人降级（转移同样走上面那个脚本）。
import { computed, onMounted, ref } from 'vue'
import { getAdminUsers, setUserRole } from '../api'
import { useUserStore } from '../stores/user'
import type { AdminUser } from '../types'

const userStore = useUserStore()

const items = ref<AdminUser[]>([])
const total = ref(0)
const page = ref(1)
const pageSize = ref(20)
const keyword = ref('')
const loading = ref(false)
const error = ref('')
const busyId = ref<number | null>(null)  // 正在改的那一行（防重复点击）

const totalPages = computed(() => Math.max(1, Math.ceil(total.value / pageSize.value)))
const myId = computed(() => userStore.user?.id ?? null)

const ROLE_LABEL: Record<string, string> = {
  superadmin: '超级管理员',
  admin: '普通管理员',
  user: '普通用户',
}

/** 该行能否被改动：超管不可改（全库唯一）、自己不可改（防自锁） */
function canEdit(u: AdminUser): boolean {
  return u.role !== 'superadmin' && u.id !== myId.value
}

function rowHint(u: AdminUser): string {
  if (u.role === 'superadmin') return '超级管理员不可被降级（转移用 tools/add_user_role.py）'
  if (u.id === myId.value) return '不能修改自己的角色'
  return ''
}

/** 拉取当前页（keyword 为空即全量列出） */
async function load() {
  loading.value = true
  error.value = ''
  try {
    const r = await getAdminUsers({
      keyword: keyword.value.trim() || undefined,
      page: page.value,
      pageSize: pageSize.value,
    })
    items.value = r.items
    total.value = r.total
  } catch (e) {
    error.value = (e as Error).message || '加载用户失败'
  } finally {
    loading.value = false
  }
}

function search() {
  page.value = 1
  load()
}

function go(delta: number) {
  const next = page.value + delta
  if (next < 1 || next > totalPages.value) return
  page.value = next
  load()
}

/** 普通管理员 ⇄ 普通用户（授权 / 取消授权）。后端还会再拦一次。 */
async function toggleRole(u: AdminUser) {
  if (busyId.value !== null || !canEdit(u)) return
  const target = u.role === 'admin' ? 'user' : 'admin'
  busyId.value = u.id
  try {
    const r = await setUserRole(u.id, target)
    u.role = r.role
  } catch (e) {
    alert((e as Error).message || '设置角色失败')
  } finally {
    busyId.value = null
  }
}

onMounted(load)
</script>

<template>
  <div>
    <div class="title-row">
      <h2 class="section-title">授权管理</h2>
      <RouterLink class="btn ghost" to="/admin">← 采集管理</RouterLink>
    </div>
    <p class="lead">
      只有<b>超级管理员</b>能进这一页。角色三档：
      <b>超级管理员</b>（管理台 + 日志 + 授权，全库唯一）、
      <b>普通管理员</b>（管理台 + 日志，不能授权）、
      <b>普通用户</b>（无管理台权限，默认）。
      本页只能在<b>普通管理员 ⇄ 普通用户</b>之间切换 —— 超级管理员不可被降级，也不能修改自己的角色。
    </p>

    <div class="toolbar">
      <form class="search" @submit.prevent="search">
        <input v-model="keyword" type="text" placeholder="搜索用户名 / 昵称" />
        <button class="btn" type="submit">搜索</button>
      </form>
      <span class="total">共 {{ total }} 个用户</span>
    </div>

    <div v-if="error" class="empty" style="color:#e23">{{ error }}</div>
    <div v-else-if="loading && !items.length" class="empty">加载用户中…</div>
    <div v-else-if="!items.length" class="empty">没有匹配的用户</div>

    <table v-else class="user-table">
      <thead>
        <tr>
          <th>用户名</th>
          <th>昵称</th>
          <th>角色</th>
          <th>注册时间</th>
          <th class="act">操作</th>
        </tr>
      </thead>
      <tbody>
        <tr v-for="u in items" :key="u.id">
          <td>
            {{ u.username }}
            <span v-if="u.id === myId" class="me">我</span>
          </td>
          <td class="dim">{{ u.nickname }}</td>
          <td>
            <span class="chip" :class="u.role">{{ ROLE_LABEL[u.role] || u.role }}</span>
          </td>
          <td class="dim">{{ u.createdAt }}</td>
          <td class="act">
            <button
              v-if="canEdit(u)"
              class="btn ghost sm"
              :disabled="busyId !== null"
              @click="toggleRole(u)"
            >
              {{ u.role === 'admin' ? '取消管理员' : '设为管理员' }}
            </button>
            <span v-else class="dim lock" :title="rowHint(u)">不可修改</span>
          </td>
        </tr>
      </tbody>
    </table>

    <div v-if="items.length" class="pager">
      <button class="btn ghost sm" :disabled="page <= 1" @click="go(-1)">上一页</button>
      <span class="dim">第 {{ page }} / {{ totalPages }} 页</span>
      <button class="btn ghost sm" :disabled="page >= totalPages" @click="go(1)">下一页</button>
    </div>
  </div>
</template>

<style scoped>
.title-row {
  display: flex;
  align-items: center;
  gap: 12px;
  flex-wrap: wrap;
  margin: 28px 0 6px;
}
.title-row .section-title { margin: 0; }
.title-row .btn { margin-left: auto; }

.lead { color: var(--text-2); font-size: 14px; margin: 0 0 16px; line-height: 1.7; }
.lead b { color: var(--primary-dark); }

.toolbar {
  display: flex;
  align-items: center;
  gap: 12px;
  flex-wrap: wrap;
  margin-bottom: 12px;
}
.search { display: flex; gap: 8px; }
.search input {
  border: 1px solid var(--border); border-radius: 8px; padding: 7px 10px;
  font-size: 14px; background: #fff; color: var(--text); min-width: 200px;
}
.total { color: var(--text-2); font-size: 13px; }

.user-table {
  width: 100%;
  border-collapse: collapse;
  background: #fff;
  border: 1px solid var(--border);
  border-radius: 14px;
  overflow: hidden;
  box-shadow: var(--shadow);
}
.user-table th,
.user-table td { padding: 10px 14px; text-align: left; font-size: 14px; }
.user-table th {
  background: var(--bg);
  font-size: 13px;
  color: var(--text-2);
  font-weight: 700;
  border-bottom: 1px solid var(--border);
}
.user-table tbody tr + tr td { border-top: 1px solid var(--border); }
.user-table .act { width: 130px; text-align: right; }
.dim { color: var(--text-2); }

.me {
  margin-left: 6px;
  font-size: 11px;
  padding: 1px 6px;
  border-radius: 999px;
  background: #f0f0f0;
  color: var(--text-2);
}
/* 三档角色配色：超管最重（绿），普通管理员次之（主题色），普通用户最浅（默认灰底） */
.chip.superadmin { background: #eef7ec; color: #2f6d1f; font-weight: 700; }
.chip.admin { background: var(--primary-soft); color: var(--primary-dark); }
.chip.user { background: #f0f0f0; color: var(--text-2); }

.lock { font-size: 13px; cursor: help; }

.btn.sm { padding: 5px 12px; font-size: 13px; }

.pager {
  display: flex;
  align-items: center;
  gap: 12px;
  justify-content: center;
  margin-top: 14px;
  font-size: 13px;
}
</style>
