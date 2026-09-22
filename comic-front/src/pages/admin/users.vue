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
import { computed, ref } from 'vue'
import { getAdminUsers, setUserRole } from '../../api'
import { useUserStore } from '../../stores/user'
import type { AdminUser } from '../../types'
import { onLoad } from '@dcloudio/uni-app'
import { setRoute, useRouter } from '../../utils/router'
import { requireRole } from '../../utils/guard'
import Layout from '../../components/Layout.vue'

const router = useRouter()
const userStore = useUserStore()

// 门卫通过前不渲染页面主体（等价 comic-web 守卫拦住时整页不出现）
const ready = ref(false)
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

onLoad(async (options) => {
  // uni 页面生命周期：登记该页对应的 web 路径（替代 vue-router 的路由状态）
  setRoute('/admin/users', options ?? {})
  // 门卫：**仅超级管理员**（等价 comic-web 的 beforeEnter: requireRole(true)）
  if (!(await requireRole(true, '/admin/users'))) return
  ready.value = true
  void load()
})

</script>

<template>
  <Layout>
    <view v-if="ready">
      <view class="title-row">
        <view class="section-title">授权管理</view>
        <view class="btn ghost u-a" @click="router.push('/admin')">← 采集管理</view>
      </view>
      <view class="lead u-p">
        只有<text class="u-b">超级管理员</text>能进这一页。角色三档：
        <text class="u-b">超级管理员</text>（管理台 + 日志 + 授权，全库唯一）、
        <text class="u-b">普通管理员</text>（管理台 + 日志，不能授权）、
        <text class="u-b">普通用户</text>（无管理台权限，默认）。
        本页只能在<text class="u-b">普通管理员 ⇄ 普通用户</text>之间切换 —— 超级管理员不可被降级，也不能修改自己的角色。
      </view>

      <view class="toolbar">
        <form class="search" @submit="search">
          <input class="u-input" v-model="keyword" type="text" placeholder="搜索用户名 / 昵称" @confirm="search" />
          <button class="btn u-button" form-type="submit">搜索</button>
        </form>
        <text class="total u-span">共 {{ total }} 个用户</text>
      </view>

      <view v-if="error" class="empty" style="color:#e23">{{ error }}</view>
      <view v-else-if="loading && !items.length" class="empty">加载用户中…</view>
      <view v-else-if="!items.length" class="empty">没有匹配的用户</view>

      <view v-else class="user-table u-table">
        <view class="u-thead">
          <view class="u-tr">
            <view class="c-user u-th">用户名</view>
            <view class="c-nick u-th">昵称</view>
            <view class="c-role u-th">角色</view>
            <view class="c-created u-th">注册时间</view>
            <view class="act u-th">操作</view>
          </view>
        </view>
        <view class="u-tbody">
          <view class="u-tr" v-for="u in items" :key="u.id">
            <view class="c-user u-td" :title="u.username">
              {{ u.username }}
              <text v-if="u.id === myId" class="me u-span">我</text>
            </view>
            <view class="c-nick dim u-td" :title="u.nickname">{{ u.nickname }}</view>
            <view class="c-role u-td">
              <text class="chip u-span" :class="u.role">{{ ROLE_LABEL[u.role] || u.role }}</text>
            </view>
            <view class="c-created dim u-td">{{ u.createdAt }}</view>
            <view class="act u-td">
              <button
                v-if="canEdit(u)"
                class="btn ghost sm u-button"
                :disabled="busyId !== null"
                @click="toggleRole(u)"
              >
                {{ u.role === 'admin' ? '取消管理员' : '设为管理员' }}
              </button>
              <text v-else class="dim lock u-span" :title="rowHint(u)">不可修改</text>
            </view>
          </view>
        </view>
      </view>

      <view v-if="items.length" class="pager">
        <button class="btn ghost sm u-button" :disabled="page <= 1" @click="go(-1)">上一页</button>
        <text class="dim u-span">第 {{ page }} / {{ totalPages }} 页</text>
        <button class="btn ghost sm u-button" :disabled="page >= totalPages" @click="go(1)">下一页</button>
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
  margin: 28px 0 6px;
}
.title-row .section-title { margin: 0; }
.title-row .btn { margin-left: auto; }

.lead { color: var(--text-2); font-size: 14px; margin: 0 0 16px; line-height: 1.7; }
.lead .u-b { color: var(--primary-dark); }

.toolbar {
  display: flex;
  align-items: center;
  gap: 12px;
  flex-wrap: wrap;
  margin-bottom: 12px;
}
.search { display: flex; gap: 8px; }
.search .u-input {
  border: 1px solid var(--border); border-radius: 8px; padding: 7px 10px;
  font-size: 14px; background: var(--card); color: var(--text); min-width: 200px;
}
.total { color: var(--text-2); font-size: 13px; }

/* ⚠️ uni 没有 <table>（小程序也不支持），原版的 table/tr/th/td 已换成 view ——
   光换标签就没有表格布局了（view 默认 block，整表会塌成竖排），这里用 flex 搭回来。
   窄屏放不下就横向滚（固定列不收缩 + 昵称列 min-width），别指望像真表格那样自动压缩。 */
.user-table {
  width: 100%;
  background: var(--card);
  border: 1px solid var(--border);
  border-radius: 14px;
  overflow-x: auto;
  box-shadow: var(--shadow);
}
.user-table .u-tr { display: flex; align-items: stretch; }
/* min-width:0 必须写：flex 项默认 min-width:auto，会被「最窄内容」撑宽 ——
   用户名/昵称一长，表头与数据行的列宽就对不上、整列错位。 */
.user-table .u-th,
.user-table .u-td { padding: 10px 14px; text-align: left; font-size: 14px; min-width: 0; }
.user-table .u-th {
  background: var(--bg);
  font-size: 13px;
  color: var(--text-2);
  font-weight: 700;
  border-bottom: 1px solid var(--border);
}
.user-table .u-tbody .u-tr + .u-tr .u-td { border-top: 1px solid var(--border); }
/* 列宽：昵称吸收剩余宽度，其余固定 */
.user-table .c-user    { flex: 0 0 180px; }
.user-table .c-nick    { flex: 1 1 0; min-width: 120px; }
/* 用户名/昵称可能很长 —— 固定列 + min-width:0 之后必须自己截断，否则文字会溢出压到相邻列上
   （原版是真表格，列宽会随内容自动变宽；view + flex 没有这个能力，只能截断，完整值放 title） */
.user-table .c-user,
.user-table .c-nick { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.user-table .c-role    { flex: 0 0 120px; }
.user-table .c-created { flex: 0 0 160px; }
.user-table .act       { flex: 0 0 130px; text-align: right; }
.dim { color: var(--text-2); }

.me {
  margin-left: 6px;
  font-size: 11px;
  padding: 1px 6px;
  border-radius: 999px;
  background: var(--mute);
  color: var(--text-2);
}
/* 三档角色配色：超管最重（绿），普通管理员次之（主题色），普通用户最浅（默认灰底） */
.chip.superadmin { background: #eef7ec; color: #2f6d1f; font-weight: 700; }
.chip.admin { background: var(--primary-soft); color: var(--primary-dark); }
.chip.user { background: var(--mute); color: var(--text-2); }

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
