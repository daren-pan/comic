<script setup lang="ts">
/**
 * 日志查询页（`/#/admin/logs`）。
 *
 * 数据来自 `log_record` 表 —— 日志由后端 logging Handler 在打日志时自动落库，
 * 所以这里看到的就是 `logs/api.log` 里那些业务日志，只是**能按条件筛、能分页**，
 * 而且不再需要"每 4 秒轮询读文件"（那是上一版的临时做法）。
 */
import { computed, ref } from 'vue'
import {
  getAdminSources,
  getLogDetail,
  getLogOptions,
  getLogRecords,
  purgeLogs,
} from '../../api'
import type { LogRecord, PickerOption, SourceInfo } from '../../types'
import { onLoad } from '@dcloudio/uni-app'
import { setRoute, useRouter } from '../../utils/router'
import { requireRole } from '../../utils/guard'
import { showAlert, showConfirm } from '../../utils/ui'
import Layout from '../../components/Layout.vue'
// 日期输入：uni 的 <input> 会把 type=date 强制成 text（白名单外），故用专用组件产出原生控件
import DateInput from '../../components/DateInput.vue'
// 下拉选择：小程序没有 <select>，统一走 uni <picker> 的封装（见该组件注释）
import Picker from '../../components/Picker.vue'

const router = useRouter()
// 门卫通过前不渲染页面主体（等价 comic-web 守卫拦住时整页不出现）
const ready = ref(false)
const items = ref<LogRecord[]>([])
const total = ref(0)
const page = ref(1)
const pageSize = ref(50)
const loading = ref(false)
const error = ref('')

const levels = ref<string[]>([])
const events = ref<string[]>([])
const sources = ref<SourceInfo[]>([])

// 筛选条件（空串 = 不限）
const f = ref({
  level: '',
  source: '',
  event: '',
  comicId: '',
  taskId: '',
  keyword: '',
  since: '',
  until: '',
})

// 展开的日志行（详情含异常堆栈，要单独取一次）
const expandedId = ref<number | null>(null)
const detail = ref<LogRecord | null>(null)

// 三个下拉的选项（首项恒为「全部」= 空串，与原生 <select> 里手写的 <option value=""> 等价）。
// picker 只认「数组 + 下标」，由 Picker 组件负责换算，这里只提供 {value,label}。
const levelOptions = computed<PickerOption[]>(() => [
  { value: '', label: '全部' },
  ...levels.value.map((lv) => ({ value: lv, label: lv })),
])
const sourceOptions = computed<PickerOption[]>(() => [
  { value: '', label: '全部' },
  ...sources.value.map((s) => ({ value: s.name, label: s.name })),
])
const eventOptions = computed<PickerOption[]>(() => [
  { value: '', label: '全部' },
  ...events.value.map((ev) => ({ value: ev, label: ev })),
])
const pageSizeOptions: PickerOption[] = [20, 50, 100, 200].map((n) => ({
  value: n,
  label: String(n),
}))

const totalPages = computed(() => Math.max(1, Math.ceil(total.value / pageSize.value)))

function params() {
  const q: Record<string, unknown> = { page: page.value, pageSize: pageSize.value }
  for (const [k, v] of Object.entries(f.value)) {
    if (v !== '' && v !== null) q[k] = v
  }
  return q
}

async function load() {
  loading.value = true
  error.value = ''
  try {
    const r = await getLogRecords(params())
    items.value = r.items
    total.value = r.total
  } catch (e) {
    error.value = (e as Error).message || '查询失败'
    items.value = []
    total.value = 0
  } finally {
    loading.value = false
  }
}

function search() {
  page.value = 1
  expandedId.value = null
  load()
}

function reset() {
  f.value = {
    level: '', source: '', event: '', comicId: '', taskId: '',
    keyword: '', since: '', until: '',
  }
  search()
}

function go(delta: number) {
  const next = page.value + delta
  if (next < 1 || next > totalPages.value) return
  page.value = next
  expandedId.value = null
  load()
}

function onPageSize() {
  search()
}

/** 展开某行：有异常类型时再取一次详情拿堆栈全文 */
async function toggle(row: LogRecord) {
  if (expandedId.value === row.id) {
    expandedId.value = null
    detail.value = null
    return
  }
  expandedId.value = row.id
  detail.value = null
  if (row.excType) {
    try {
      detail.value = await getLogDetail(row.id)
    } catch {
      detail.value = null
    }
  }
}

async function doPurge() {
  const days = 30
  // 用 utils/ui 的跨端弹窗：小程序没有 window，window.confirm/alert 会直接抛错
  if (!(await showConfirm(`删除 ${days} 天前的日志？此操作不可撤销。`, '清理日志'))) return
  try {
    const r = await purgeLogs(days)
    showAlert(`已删除 ${r.deleted} 条`)
    search()
  } catch (e) {
    showAlert((e as Error).message || '清理失败')
  }
}

onLoad(async (options) => {
  // uni 页面生命周期：登记该页对应的 web 路径（替代 vue-router 的路由状态）
  setRoute('/admin/logs', options ?? {})
  // 门卫：未登录 / 角色不够 → 跳走并终止本页加载（等价 comic-web 的 beforeEnter: requireRole(false)）
  if (!(await requireRole(false, '/admin/logs'))) return
  ready.value = true

  const [opts, srcs] = await Promise.all([
    getLogOptions().catch(() => ({ levels: [], events: [] })),
    getAdminSources().catch(() => [] as SourceInfo[]),
  ])
  levels.value = opts.levels
  events.value = opts.events
  sources.value = srcs
  load()
})

</script>

<template>
  <Layout>
    <view v-if="ready">
      <view class="title-row">
        <view class="section-title">日志查询</view>
        <button class="btn ghost u-button" @click="doPurge">清理 30 天前</button>
        <view class="btn ghost u-a" @click="router.push('/admin')">← 返回采集管理</view>
      </view>
      <view class="lead u-p">
        采集 / 巡检 / 按需导入 / 读图的运行日志（与后端 <text class="u-code">logs/api.log</text> 同一批记录，已落库）。
        失败日志的正文带作品 id 与名称，点某行展开详情（含异常堆栈全文）。
      </view>

      <!-- 筛选条件 -->
      <view class="filters">
        <view class="u-label">级别
          <Picker
            class="u-select"
            :model-value="f.level"
            :options="levelOptions"
            @update:model-value="f.level = String($event); search()"
          />
        </view>
        <view class="u-label">源站
          <Picker
            class="u-select"
            :model-value="f.source"
            :options="sourceOptions"
            @update:model-value="f.source = String($event); search()"
          />
        </view>
        <view class="u-label">事件
          <Picker
            class="u-select"
            :model-value="f.event"
            :options="eventOptions"
            @update:model-value="f.event = String($event); search()"
          />
        </view>
        <view class="u-label">作品 ID
          <input class="u-input" v-model="f.comicId" type="number" min="1" placeholder="如 151" @confirm="search" />
        </view>
        <view class="u-label">任务 ID
          <input class="u-input" v-model="f.taskId" placeholder="如 inspect-2-…" @confirm="search" />
        </view>
        <view class="u-label">起始
          <DateInput :model-value="f.since" @update:model-value="f.since = $event" />
        </view>
        <view class="u-label">截止（含当天）
          <DateInput :model-value="f.until" @update:model-value="f.until = $event" />
        </view>
        <view class="grow u-label">关键字
          <input class="u-input" v-model="f.keyword" placeholder="正文 / 作品名 / 章节名 / 原因" @confirm="search" />
        </view>
        <button class="btn u-button" @click="search">查询</button>
        <button class="btn ghost u-button" @click="reset">重置</button>
      </view>

      <view v-if="error" class="empty" style="color:#e23">{{ error }}</view>

      <!-- 列表 -->
      <view class="table-wrap">
        <view class="u-table">
          <view class="u-thead">
            <view class="u-tr">
              <view class="c-time u-th">时间</view>
              <view class="c-level u-th">级别</view>
              <view class="c-event u-th">事件</view>
              <view class="c-src u-th">源站</view>
              <view class="c-title u-th">作品</view>
              <view class="c-chapter u-th">章节</view>
              <view class="c-pages u-th">页数</view>
              <view class="msg u-th">消息</view>
            </view>
          </view>
          <view class="u-tbody">
            <template v-for="row in items" :key="row.id">
              <view class="row u-tr" :class="{ open: expandedId === row.id }" @click="toggle(row)">
                <view class="c-time mono u-td">{{ row.createdAt }}</view>
                <view class="c-level u-td"><text class="badge u-span" :class="row.level.toLowerCase()">{{ row.level }}</text></view>
                <view class="c-event mono u-td">{{ row.event || '—' }}</view>
                <view class="c-src u-td">{{ row.source || '—' }}</view>
                <view class="c-title u-td" :title="row.comicTitle">{{ row.comicTitle || (row.comicId ? `#${row.comicId}` : '—') }}</view>
                <view class="c-chapter u-td" :title="row.chapterTitle">{{ row.chapterTitle || (row.chapterId ? `#${row.chapterId}` : '—') }}</view>
                <view class="c-pages u-td">{{ row.pages ?? '—' }}</view>
                <view class="msg u-td" :title="row.message">{{ row.message }}</view>
              </view>
              <view v-if="expandedId === row.id" class="detail-row u-tr">
                <view class="u-td">
                  <view class="detail">
                    <view class="kv"><text class="u-b">记录器</text><text class="u-span">{{ row.logger }}</text></view>
                    <view class="kv" v-if="row.taskId"><text class="u-b">任务</text><text class="u-span">{{ row.taskType }} · {{ row.taskId }}</text></view>
                    <view class="kv" v-if="row.reason"><text class="u-b">原因</text><text class="u-span">{{ row.reason }}</text></view>
                    <view class="kv" v-if="row.endpoint"><text class="u-b">接口/地址</text><text class="mono u-span">{{ row.endpoint }}</text></view>
                    <view class="kv full"><text class="u-b">消息</text><text class="u-span">{{ row.message }}</text></view>
                    <template v-if="row.excType">
                      <view class="kv"><text class="u-b">异常</text><text class="u-span">{{ row.excType }}</text></view>
                      <view class="trace">{{ detail?.excText || '（读取堆栈中…）' }}</view>
                    </template>
                  </view>
                </view>
              </view>
            </template>
            <view class="u-tr" v-if="!loading && !items.length && !error">
              <view class="empty u-td">没有符合条件的日志</view>
            </view>
            <view class="u-tr" v-if="loading">
              <view class="empty u-td">查询中…</view>
            </view>
          </view>
        </view>
      </view>

      <!-- 分页 -->
      <view class="pager">
        <text class="u-span">共 {{ total }} 条 · 第 {{ page }} / {{ totalPages }} 页</text>
        <view class="size u-label">每页
          <Picker
            class="u-select"
            :model-value="pageSize"
            :options="pageSizeOptions"
            @update:model-value="pageSize = Number($event); onPageSize()"
          />
        </view>
        <button class="btn ghost u-button" :disabled="page <= 1" @click="go(-1)">上一页</button>
        <button class="btn ghost u-button" :disabled="page >= totalPages" @click="go(1)">下一页</button>
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
.title-row .btn { text-decoration: none; }
.title-row .btn:first-of-type { margin-left: auto; }

.lead { color: var(--text-2); font-size: 14px; margin: 0 0 14px; }
.lead .u-code { background: var(--mute); border-radius: 4px; padding: 1px 5px; }

.filters {
  display: flex;
  flex-wrap: wrap;
  align-items: flex-end;
  gap: 10px 12px;
  background: var(--card);
  border: 1px solid var(--border);
  border-radius: 14px;
  padding: 14px 16px;
  margin-bottom: 14px;
}
.filters .u-label {
  display: flex;
  flex-direction: column;
  gap: 4px;
  font-size: 12px;
  color: var(--text-2);
}
.filters .grow { flex: 1; min-width: 200px; }
/* `.date-inp`：日期控件是 DateInput 产出的**原生 .u-input**，uni 会把上面的 `.u-input` 改写成
   `uni-input`、匹配不到它，故这里额外挂上它的类名。 */
.filters .u-input,
.filters .date-inp {
  font: inherit;
  font-size: 13px;
  color: var(--text);
  background: var(--card);
  border: 1px solid var(--border);
  border-radius: 8px;
  padding: 6px 8px;
}
/* Picker 组件自带边框/内边距 → 这里只给宽度，再画一遍会变双边框 */
.filters .u-select { min-width: 96px; }
.filters .date-inp { min-width: 138px; }

.table-wrap {
  background: var(--card);
  border: 1px solid var(--border);
  border-radius: 14px;
  overflow: auto;
  max-height: 62vh;
}
/* ⚠️ uni 没有 <table>（小程序也不支持），原版的 table/tr/th/td 已换成 view ——
   但**光换标签就没有表格布局了**（view 默认 block，于是每个单元格各占一行、整表塌成竖排）。
   这里用 flex 自己把表格搭回来（`display:table*` 在小程序不可靠，flex 三端都稳）。
   列宽由下面的 flex-basis 显式给，最后一列「消息」吃掉剩余宽度。 */
.u-table { width: 100%; font-size: 13px; }
.u-tr { display: flex; align-items: stretch; }
/* min-width:0 必须写：flex 项默认 min-width:auto，会被「最窄内容」撑宽 ——
   表头文字短、数据文字长（如时间列），于是表头与数据行的列宽对不上、整列错位。 */
.u-th, .u-td { text-align: left; padding: 8px 10px; border-bottom: 1px solid var(--border); min-width: 0; }
/* 表头吸顶：sticky 挂在 .u-thead（不是每个 .u-th）上 —— 它的包含块是**整张表**，才有可吸顶的
   余量；挂在单元格上会被「只有一行高」的包含块锁死，等于不生效。 */
.u-thead {
  position: sticky;
  top: 0;
  z-index: 1;
  background: var(--surface-2);
}
.u-thead .u-th { background: var(--surface-2); color: var(--text-2); font-weight: 600; white-space: nowrap; }
.row { cursor: pointer; }
.row:hover { background: var(--surface-2); }
.row.open { background: var(--primary-soft); }
.mono { font-family: ui-monospace, Consolas, 'Cascadia Mono', monospace; }
/* 展开行与空态行只有一格 → 让它占满整行（等价原版的 colspan="8"） */
.u-tr > .empty { flex: 1; }
/* 列宽（固定列不收缩；.msg 吸收剩余宽度，min-width 保证窄屏下仍可读、由 .table-wrap 横向滚） */
.c-time    { flex: 0 0 148px; white-space: nowrap; color: var(--text-2); }
.c-level   { flex: 0 0 76px; }
.c-event   { flex: 0 0 128px; white-space: nowrap; }
.c-src     { flex: 0 0 104px; white-space: nowrap; }
.c-title   { flex: 0 0 152px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.c-chapter { flex: 0 0 120px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.c-pages   { flex: 0 0 56px; white-space: nowrap; }
.msg       { flex: 1 1 0; min-width: 160px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }

.badge {
  display: inline-block;
  border-radius: 6px;
  padding: 1px 7px;
  font-size: 11px;
  background: #eef0f2;
  color: #555;
}
.badge.warning { background: #fff3e6; color: #b25f00; }
.badge.error { background: #fdeceb; color: #c0392b; }

.detail-row .u-td { flex: 1; background: var(--surface-2); }
.detail { display: grid; grid-template-columns: repeat(auto-fit, minmax(240px, 1fr)); gap: 6px 18px; }
.kv { display: flex; gap: 8px; font-size: 13px; }
.kv .u-b { color: var(--text-2); font-weight: 600; flex: 0 0 52px; }
.kv.full { grid-column: 1 / -1; }
.kv .u-span { word-break: break-all; }
.trace {
  grid-column: 1 / -1;
  margin: 6px 0 0;
  padding: 10px 12px;
  background: var(--card);
  border: 1px solid var(--border);
  border-radius: 10px;
  font-family: ui-monospace, Consolas, 'Cascadia Mono', monospace;
  font-size: 12px;
  line-height: 1.65;
  max-height: 260px;
  overflow: auto;
  white-space: pre-wrap;
  word-break: break-all;
  color: var(--text);
}

.pager {
  display: flex;
  align-items: center;
  gap: 10px;
  margin-top: 12px;
  font-size: 13px;
  color: var(--text-2);
}
.pager .size { display: flex; align-items: center; gap: 6px; }
/* Picker 组件自带盒子样式（见 components/Picker.vue），这里只约束宽度 */
.pager .u-select { min-width: 72px; }
</style>
