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
import { useRouter } from 'vue-router'
import { showAlert } from '../utils/ui'
import { usePagedList } from '../composables/usePagedList'
import Layout from '../components/Layout.vue'
import Pager from '../components/Pager.vue'

const router = useRouter()
const userStore = useUserStore()

// 挂载后置 true 渲染页面主体（门卫由路由层 beforeEnter 承担）
const ready = ref(false)   // ← 这是「门卫过没过」的标志，与列表状态无关
const keyword = ref('')
const busyId = ref<number | null>(null)  // 正在改的那一行（防重复点击）

/**
 * 列表状态机（分页 / 竞态 / 失败回退都在里面）—— 2026-10-13 抽自多页逐字重复的代码。
 * ⚠️ `immediate: false`：**门卫通过后**才拉数据（见 `onLoad`）。
 */
const { items, total, page, loading, error, totalPages, goPage, reload } = usePagedList(
  (p, ps) => getAdminUsers({ keyword: keyword.value.trim() || undefined, page: p, pageSize: ps }),
  { pageSize: 20, immediate: false },
)

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

function search() {
  reload()   // 回第一页重拉（`reload` 内部会把页码归 1）
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
    void showAlert((e as Error).message || '设置角色失败')
  } finally {
    busyId.value = null
  }
}

onMounted(async () => {
  ready.value = true
  reload()
})

</script>

<template>
  <Layout>
    <div v-if="ready">
      <div class="title-row">
        <div class="section-title">授权管理</div>
        <div class="btn ghost u-a" @click="router.push('/admin')">← 采集管理</div>
      </div>
      <div class="lead u-p">
        只有<span class="u-b">超级管理员</span>能进这一页。角色三档：
        <span class="u-b">超级管理员</span>（管理台 + 日志 + 授权，全库唯一）、
        <span class="u-b">普通管理员</span>（管理台 + 日志，不能授权）、
        <span class="u-b">普通用户</span>（无管理台权限，默认）。
        本页只能在<span class="u-b">普通管理员 ⇄ 普通用户</span>之间切换 —— 超级管理员不可被降级，也不能修改自己的角色。
      </div>

      <div class="toolbar">
        <form class="search" @submit.prevent="search">
          <input class="u-input" v-model="keyword" type="text" placeholder="搜索用户名 / 昵称" />
          <button class="btn u-button" type="submit">搜索</button>
        </form>
        <span class="total u-span">共 {{ total }} 个用户</span>
      </div>

      <div v-if="error" class="empty" style="color:#e23">{{ error }}</div>
      <div v-else-if="loading && !items.length" class="empty">加载用户中…</div>
      <div v-else-if="!items.length" class="empty">没有匹配的用户</div>

      <div v-else class="user-table u-table">
        <div class="u-thead">
          <div class="u-tr">
            <div class="c-user u-th">用户名</div>
            <div class="c-nick u-th">昵称</div>
            <div class="c-role u-th">角色</div>
            <div class="c-created u-th">注册时间</div>
            <div class="act u-th">操作</div>
          </div>
        </div>
        <div class="u-tbody">
          <div class="u-tr" v-for="u in items" :key="u.id">
            <!-- `.lbl` 是窄屏专用字段标签（宽屏 display:none）——桌面靠表头，卡片靠它 -->
            <div class="c-user u-td" :title="u.username">
              <span class="lbl u-span">用户名</span>
              <span class="val u-span">{{ u.username }}</span>
              <span v-if="u.id === myId" class="me u-span">我</span>
            </div>
            <div class="c-nick dim u-td" :title="u.nickname">
              <span class="lbl u-span">昵称</span>
              <span class="val u-span">{{ u.nickname }}</span>
            </div>
            <div class="c-role u-td">
              <span class="lbl u-span">角色</span>
              <span class="chip u-span" :class="u.role">{{ ROLE_LABEL[u.role] || u.role }}</span>
            </div>
            <div class="c-created dim u-td">
              <span class="lbl u-span">注册时间</span>
              <span class="val u-span">{{ u.createdAt }}</span>
            </div>
            <div class="act u-td">
              <button
                v-if="canEdit(u)"
                class="btn ghost sm u-button"
                :disabled="busyId !== null"
                @click="toggleRole(u)"
              >
                {{ u.role === 'admin' ? '取消管理员' : '设为管理员' }}
              </button>
              <span v-else class="dim lock u-span" :title="rowHint(u)">不可修改</span>
            </div>
          </div>
        </div>
      </div>

      <Pager v-if="items.length" :page="page" :total-pages="totalPages" @change="goPage" />
    </div>
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

/* ⚠️ uni 没有 <table>，原版的 table/tr/th/td 已换成 view ——
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
/* 窄屏专用字段标签：宽屏隐藏 —— 桌面表格有表头，不需要每格再写一遍标签。
   ⚠️ 必须在下面的 @media 之前：两条选择器特异性相同，靠源码顺序决出胜负。 */
.user-table .lbl { display: none; }
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

/* ---- 窄屏（≤860px）：表格 → 卡片，杜绝横向滚动条 ----
   5 列固定宽合计 ≈ 710px（180 + 昵称≥120 + 120 + 160 + 130），窄屏可视只有 ~343px。
   与日志页同款处理：隐藏表头、行变纵向卡片、每段「标签 + 值」。
   本页行内直接带操作按钮、没有「点开才看得到」的字段，故不需要展开。
   断点与 `Layout.vue` 一致（只有 CSS 一处，脚本里没有宽度判断）。 */
@media (max-width: 860px) {
  .user-table { overflow-x: visible; }
  .user-table .u-thead { display: none; }

  .user-table .u-tr {
    display: flex;
    flex-direction: column;
    align-items: stretch;
    gap: 5px;
    padding: 10px 12px;
  }
  .user-table .u-th,
  .user-table .u-td { padding: 0; border-top: 0; }
  /* ⚠️ 重置列宽：桌面 `flex: 0 0 180px` 是**主轴**方向的基准，卡片改纵向后主轴变成高度 ——
     不重置的话每段会被钉成 180px 高。 */
  .user-table .c-user,
  .user-table .c-nick,
  .user-table .c-role,
  .user-table .c-created,
  .user-table .act { flex: none; min-width: 0; }

  /* 每段「标签 + 值」：标签定宽、值吃掉剩余宽度 */
  .user-table .u-td { display: flex; align-items: center; gap: 8px; }
  .user-table .lbl { display: block; flex: 0 0 60px; font-size: 12px; color: var(--text-2); }
  .user-table .u-td .val { flex: 1 1 0; min-width: 0; }

  /* 卡片里不再单行截断（宽度够，换行比省略号好读） */
  .user-table .c-user,
  .user-table .c-nick { white-space: normal; }
  /* 操作按钮独占最后一行（`.act` 也是 `.u-td`，已被上面的 flex 规则接管） */
  .user-table .act { padding-top: 4px; }

  .pager { flex-wrap: wrap; }
}
</style>
