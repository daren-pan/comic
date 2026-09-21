<script setup lang="ts">
/**
 * 日志查询页（`/#/admin/logs`）。
 *
 * 数据来自 `log_record` 表 —— 日志由后端 logging Handler 在打日志时自动落库，
 * 所以这里看到的就是 `logs/api.log` 里那些业务日志，只是**能按条件筛、能分页**，
 * 而且不再需要"每 4 秒轮询读文件"（那是上一版的临时做法）。
 */
import { computed, onMounted, ref } from 'vue'
import {
  getAdminSources,
  getLogDetail,
  getLogOptions,
  getLogRecords,
  purgeLogs,
} from '../api'
import type { LogRecord, SourceInfo } from '../types'

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
  if (!window.confirm(`删除 ${days} 天前的日志？此操作不可撤销。`)) return
  try {
    const r = await purgeLogs(days)
    window.alert(`已删除 ${r.deleted} 条`)
    search()
  } catch (e) {
    window.alert((e as Error).message || '清理失败')
  }
}

onMounted(async () => {
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
  <div>
    <div class="title-row">
      <h2 class="section-title">日志查询</h2>
      <button class="btn ghost" @click="doPurge">清理 30 天前</button>
      <RouterLink class="btn ghost" to="/admin">← 返回采集管理</RouterLink>
    </div>
    <p class="lead">
      采集 / 巡检 / 按需导入 / 读图的运行日志（与后端 <code>logs/api.log</code> 同一批记录，已落库）。
      失败日志的正文带作品 id 与名称，点某行展开详情（含异常堆栈全文）。
    </p>

    <!-- 筛选条件 -->
    <div class="filters">
      <label>级别
        <select v-model="f.level" @change="search">
          <option value="">全部</option>
          <option v-for="lv in levels" :key="lv" :value="lv">{{ lv }}</option>
        </select>
      </label>
      <label>源站
        <select v-model="f.source" @change="search">
          <option value="">全部</option>
          <option v-for="s in sources" :key="s.name" :value="s.name">{{ s.name }}</option>
        </select>
      </label>
      <label>事件
        <select v-model="f.event" @change="search">
          <option value="">全部</option>
          <option v-for="ev in events" :key="ev" :value="ev">{{ ev }}</option>
        </select>
      </label>
      <label>作品 ID
        <input v-model="f.comicId" type="number" min="1" placeholder="如 151" @keyup.enter="search" />
      </label>
      <label>任务 ID
        <input v-model="f.taskId" placeholder="如 inspect-2-…" @keyup.enter="search" />
      </label>
      <label>起始
        <input v-model="f.since" type="date" />
      </label>
      <label>截止（含当天）
        <input v-model="f.until" type="date" />
      </label>
      <label class="grow">关键字
        <input v-model="f.keyword" placeholder="正文 / 作品名 / 章节名 / 原因" @keyup.enter="search" />
      </label>
      <button class="btn" @click="search">查询</button>
      <button class="btn ghost" @click="reset">重置</button>
    </div>

    <div v-if="error" class="empty" style="color:#e23">{{ error }}</div>

    <!-- 列表 -->
    <div class="table-wrap">
      <table>
        <thead>
          <tr>
            <th class="c-time">时间</th>
            <th class="c-level">级别</th>
            <th class="c-event">事件</th>
            <th class="c-src">源站</th>
            <th class="c-title">作品</th>
            <th class="c-chapter">章节</th>
            <th class="c-pages">页数</th>
            <th>消息</th>
          </tr>
        </thead>
        <tbody>
          <template v-for="row in items" :key="row.id">
            <tr class="row" :class="{ open: expandedId === row.id }" @click="toggle(row)">
              <td class="c-time mono">{{ row.createdAt }}</td>
              <td class="c-level"><span class="badge" :class="row.level.toLowerCase()">{{ row.level }}</span></td>
              <td class="c-event mono">{{ row.event || '—' }}</td>
              <td class="c-src">{{ row.source || '—' }}</td>
              <td class="c-title" :title="row.comicTitle">{{ row.comicTitle || (row.comicId ? `#${row.comicId}` : '—') }}</td>
              <td class="c-chapter" :title="row.chapterTitle">{{ row.chapterTitle || (row.chapterId ? `#${row.chapterId}` : '—') }}</td>
              <td class="c-pages">{{ row.pages ?? '—' }}</td>
              <td class="msg" :title="row.message">{{ row.message }}</td>
            </tr>
            <tr v-if="expandedId === row.id" class="detail-row">
              <td colspan="8">
                <div class="detail">
                  <div class="kv"><b>记录器</b><span>{{ row.logger }}</span></div>
                  <div class="kv" v-if="row.taskId"><b>任务</b><span>{{ row.taskType }} · {{ row.taskId }}</span></div>
                  <div class="kv" v-if="row.reason"><b>原因</b><span>{{ row.reason }}</span></div>
                  <div class="kv" v-if="row.endpoint"><b>接口/地址</b><span class="mono">{{ row.endpoint }}</span></div>
                  <div class="kv full"><b>消息</b><span>{{ row.message }}</span></div>
                  <template v-if="row.excType">
                    <div class="kv"><b>异常</b><span>{{ row.excType }}</span></div>
                    <pre class="trace">{{ detail?.excText || '（读取堆栈中…）' }}</pre>
                  </template>
                </div>
              </td>
            </tr>
          </template>
          <tr v-if="!loading && !items.length && !error">
            <td colspan="8" class="empty">没有符合条件的日志</td>
          </tr>
          <tr v-if="loading">
            <td colspan="8" class="empty">查询中…</td>
          </tr>
        </tbody>
      </table>
    </div>

    <!-- 分页 -->
    <div class="pager">
      <span>共 {{ total }} 条 · 第 {{ page }} / {{ totalPages }} 页</span>
      <label class="size">每页
        <select v-model.number="pageSize" @change="onPageSize">
          <option :value="20">20</option>
          <option :value="50">50</option>
          <option :value="100">100</option>
          <option :value="200">200</option>
        </select>
      </label>
      <button class="btn ghost" :disabled="page <= 1" @click="go(-1)">上一页</button>
      <button class="btn ghost" :disabled="page >= totalPages" @click="go(1)">下一页</button>
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
.title-row .btn { text-decoration: none; }
.title-row .btn:first-of-type { margin-left: auto; }

.lead { color: var(--text-2); font-size: 14px; margin: 0 0 14px; }
.lead code { background: #f0ede8; border-radius: 4px; padding: 1px 5px; }

.filters {
  display: flex;
  flex-wrap: wrap;
  align-items: flex-end;
  gap: 10px 12px;
  background: #fff;
  border: 1px solid var(--border);
  border-radius: 14px;
  padding: 14px 16px;
  margin-bottom: 14px;
}
.filters label {
  display: flex;
  flex-direction: column;
  gap: 4px;
  font-size: 12px;
  color: var(--text-2);
}
.filters .grow { flex: 1; min-width: 200px; }
.filters input,
.filters select {
  font: inherit;
  font-size: 13px;
  color: var(--text);
  background: #fff;
  border: 1px solid var(--border);
  border-radius: 8px;
  padding: 6px 8px;
}
.filters input[type='date'] { min-width: 138px; }

.table-wrap {
  background: #fff;
  border: 1px solid var(--border);
  border-radius: 14px;
  overflow: auto;
  max-height: 62vh;
}
table { width: 100%; border-collapse: collapse; font-size: 13px; }
th, td { text-align: left; padding: 8px 10px; border-bottom: 1px solid var(--border); vertical-align: top; }
thead th {
  position: sticky;
  top: 0;
  z-index: 1;
  background: #fbfaf8;
  color: var(--text-2);
  font-weight: 600;
  white-space: nowrap;
}
.row { cursor: pointer; }
.row:hover { background: #fdfbf9; }
.row.open { background: #fff8f4; }
.mono { font-family: ui-monospace, Consolas, 'Cascadia Mono', monospace; }
.c-time { white-space: nowrap; color: var(--text-2); }
.c-event, .c-src, .c-pages { white-space: nowrap; }
.c-title, .c-chapter { max-width: 160px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.msg { max-width: 520px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }

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

.detail-row td { background: #fdfbf9; }
.detail { display: grid; grid-template-columns: repeat(auto-fit, minmax(240px, 1fr)); gap: 6px 18px; }
.kv { display: flex; gap: 8px; font-size: 13px; }
.kv b { color: var(--text-2); font-weight: 600; flex: 0 0 52px; }
.kv.full { grid-column: 1 / -1; }
.kv span { word-break: break-all; }
.trace {
  grid-column: 1 / -1;
  margin: 6px 0 0;
  padding: 10px 12px;
  background: #fff;
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
.pager select {
  font: inherit;
  font-size: 13px;
  border: 1px solid var(--border);
  border-radius: 8px;
  padding: 4px 6px;
  background: #fff;
  color: var(--text);
}
</style>
