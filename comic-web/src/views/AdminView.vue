<script setup lang="ts">
import { onMounted, onBeforeUnmount, reactive, ref } from 'vue'
import {
  getAdminSources,
  toggleAdminSource,
  startAdminSync,
  startAdminTransfer,
  getAdminTask,
} from '../api'
import type { AdminTask, SourceInfo } from '../types'

// 每个源的采集/转存操作表单状态（独立参数）
interface SourceVM {
  info: SourceInfo
  syncMode: 'incremental' | 'full'
  syncSince: string   // 起始日期（yyyy-MM-dd 或空）
  syncLimit: string   // 数量（空=不限）
  transferSince: string
  transferUntil: string
  transferLimit: string
  running: boolean    // 是否正在触发（防重复点击）
}

const sources = ref<SourceVM[]>([])
const loaded = ref(false)
const error = ref('')
const activeTasks = ref<Record<string, AdminTask>>({}) // taskId -> 状态
const taskOrder = ref<string[]>([])                    // 保持触发顺序
const taskMeta = ref<Record<string, { source: string; mode?: string }>>({}) // 历史记录附加信息（源/模式）

// 任务完成/失败 toast 提示
const toast = ref<{ typeLabel: string; statusLabel: string; status: string; text: string; detail: string } | null>(null)
let toastTimer = 0

// 轮询句柄（组件卸载时清理）
const pollTimers = new Set<number>()

function fmtTime(iso: string | null): string {
  if (!iso) return '—'
  const d = new Date(iso)
  const pad = (n: number) => String(n).padStart(2, '0')
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())} ${pad(d.getHours())}:${pad(d.getMinutes())}`
}

function fmtInterval(sec: number): string {
  if (sec < 60) return `${sec}s`
  if (sec % 3600 === 0) return `${sec / 3600}h`
  return `${Math.round(sec / 60)}min`
}

async function load() {
  error.value = ''
  try {
    const list = await getAdminSources()
    sources.value = list.map((info) => ({
      info,
      syncMode: 'incremental',
      syncSince: '',
      syncLimit: '',
      transferSince: '',
      transferUntil: '',
      transferLimit: '',
      running: false,
    }))
    loaded.value = true
  } catch (e) {
    error.value = (e as Error).message || '加载数据源失败'
  }
}

async function toggleSource(vm: SourceVM) {
  try {
    const r = await toggleAdminSource(vm.info.name)
    vm.info.enabled = r.enabled
  } catch (e) {
    alert((e as Error).message || '切换失败')
  }
}

/** 任务结束（完成/失败）时弹出右上角结果提示 */
function showToast(type: string, t: AdminTask) {
  const typeLabel = type === 'sync' ? '采集' : '转存'
  const statusLabel = t.status === 'done' ? '完成' : '失败'
  toast.value = {
    typeLabel,
    statusLabel,
    status: t.status,
    text: taskResultText(t) || t.message,
    detail: taskResultDetail(t),
  }
  clearTimeout(toastTimer)
  toastTimer = window.setTimeout(() => { toast.value = null }, 6000)
}

/** 轮询单个任务直到 done/failed */
function watchTask(taskId: string, type: string) {
  const poll = async () => {
    try {
      const t = await getAdminTask(taskId)
      const prev = activeTasks.value[taskId]
      activeTasks.value[taskId] = t
      // 任务刚结束（running -> done/failed）→ 弹出结果提示
      if (prev && prev.status === 'running' && t.status !== 'running') {
        showToast(type, t)
      }
      if (t.status === 'running') {
        const timer = window.setTimeout(poll, 1500)
        pollTimers.add(timer)
      }
    } catch {
      // 查询失败则保留最后状态，不再重试
    }
  }
  poll()
}

function trackTask(taskId: string, type: string, source: string, mode?: string) {
  if (!taskOrder.value.includes(taskId)) taskOrder.value.unshift(taskId)
  taskMeta.value[taskId] = { source, mode }
  // 占位初始态，确保首次轮询能检测到 running -> 结束 的跳变
  activeTasks.value[taskId] = {
    id: taskId, type: type as AdminTask['type'], status: 'running', message: '运行中',
    result: null, startedAt: new Date().toISOString(), finishedAt: null,
  }
  watchTask(taskId, type)
}

/** 清空历史消息 */
function clearHistory() {
  taskOrder.value = []
  activeTasks.value = {}
  taskMeta.value = {}
}

async function runSync(vm: SourceVM) {
  if (vm.running) return
  vm.running = true
  try {
    const body = {
      source: vm.info.name,
      mode: vm.syncMode,
      since: vm.syncSince || undefined,
      limit: vm.syncLimit ? Number(vm.syncLimit) : undefined,
    }
    const { taskId } = await startAdminSync(body)
    trackTask(taskId, 'sync', vm.info.name, vm.syncMode)
  } catch (e) {
    alert((e as Error).message || '触发采集失败')
  } finally {
    vm.running = false
  }
}

async function runTransfer(vm: SourceVM) {
  if (vm.running) return
  vm.running = true
  try {
    const body = {
      source: vm.info.name,
      since: vm.transferSince || undefined,
      until: vm.transferUntil || undefined,
      limit: vm.transferLimit ? Number(vm.transferLimit) : undefined,
    }
    const { taskId } = await startAdminTransfer(body)
    trackTask(taskId, 'transfer', vm.info.name)
  } catch (e) {
    alert((e as Error).message || '触发懒转存失败')
  } finally {
    vm.running = false
  }
}

/** 任务结果摘要文本 */
function taskResultText(t: AdminTask): string {
  if (t.status !== 'done' || !t.result) return ''
  if (t.type === 'sync') {
    const s = t.result.stats as Record<string, number> | undefined
    if (s) return `扫描 ${s.total_seen} 部 | 新增 ${s.new_comics} | 更新 ${s.updated_comics} | 新增章节 ${s.new_chapters} | 失败 ${s.failed}`
  }
  const r = t.result as Record<string, number>
  return `转存: 检查 ${r.checked ?? 0} | 成功 ${r.transferred ?? 0} | 失败 ${r.failed ?? 0}`
}

function taskResultDetail(t: AdminTask): string {
  if (t.status !== 'done' || !t.result) return ''
  if (t.type === 'sync') {
    const db = t.result.db as Record<string, number> | undefined
    return db ? `库内: ${db.comics} 部 / ${db.chapters} 章 / ${db.pages} 页` : ''
  }
  const pb = t.result.pagesByStatus as Record<string, number> | undefined
  if (pb) {
    const parts = Object.entries(pb).map(([k, v]) => `${k} ${v}`).join(' · ')
    return `页面状态: ${parts}`
  }
  return ''
}

onMounted(load)
onBeforeUnmount(() => {
  pollTimers.forEach((t) => clearTimeout(t))
  pollTimers.clear()
  clearTimeout(toastTimer)
})
</script>

<template>
  <div>
    <h2 class="section-title">采集管理</h2>
    <p class="lead">手动触发各数据源的采集与懒转存；关闭的源将拒绝触发采集。参数留空表示使用默认值。</p>

    <div v-if="error" class="empty" style="color:#e23">{{ error }}</div>
    <div v-else-if="!loaded" class="empty">加载数据源中…</div>

    <!-- 数据源卡片 -->
    <div v-else class="grid">
      <div v-for="vm in sources" :key="vm.info.name" class="card">
        <div class="card-head">
          <div class="head-left">
            <span class="src-name">{{ vm.info.name }}</span>
            <span class="chip pri" :class="vm.info.priority">{{ vm.info.priority === 'primary' ? '主源' : '备源' }}</span>
          </div>
          <label class="switch" :title="vm.info.enabled ? '点击关闭采集' : '点击开启采集'">
            <input type="checkbox" :checked="vm.info.enabled" @change="toggleSource(vm)" />
            <span class="slider"></span>
          </label>
        </div>

        <div class="card-meta">
          <span>库内 <b>{{ vm.info.comicCount }}</b> 部</span>
          <span>间隔 <b>{{ fmtInterval(vm.info.interval) }}</b></span>
          <span>上次同步 <b>{{ fmtTime(vm.info.lastSync) }}</b></span>
        </div>

        <!-- 采集区 -->
        <div class="panel">
          <div class="panel-title">采集</div>
          <div class="row-inputs">
            <label>模式
              <select v-model="vm.syncMode">
                <option value="incremental">增量</option>
                <option value="full">全量</option>
              </select>
            </label>
            <label>起始日期
              <input v-model="vm.syncSince" type="date" />
            </label>
            <label>数量
              <input v-model="vm.syncLimit" type="number" min="1" placeholder="不限" />
            </label>
          </div>
          <button class="btn" :disabled="vm.running || !vm.info.enabled" @click="runSync(vm)">
            {{ vm.running ? '运行中…' : '触发采集' }}
          </button>
        </div>

        <!-- 懒转存区 -->
        <div class="panel">
          <div class="panel-title">懒转存</div>
          <div class="row-inputs">
            <label>起始
              <input v-model="vm.transferSince" type="date" />
            </label>
            <label>截止
              <input v-model="vm.transferUntil" type="date" />
            </label>
            <label>数量
              <input v-model="vm.transferLimit" type="number" min="1" placeholder="200" />
            </label>
          </div>
          <button class="btn ghost" :disabled="vm.running" @click="runTransfer(vm)">
            {{ vm.running ? '运行中…' : '触发转存' }}
          </button>
        </div>
      </div>
    </div>

    <!-- 历史消息 -->
    <template v-if="taskOrder.length">
      <div class="task-bar">
        <h2 class="section-title">历史消息</h2>
        <button class="btn ghost sm" @click="clearHistory">清空历史</button>
      </div>
      <div class="task-list">
        <div v-for="tid in taskOrder" :key="tid" class="task" v-if="activeTasks[tid]">
          <div class="task-head">
            <span class="chip" :class="activeTasks[tid].type">
              {{ activeTasks[tid].type === 'sync' ? '采集' : '转存' }}
            </span>
            <span class="status" :class="activeTasks[tid].status">
              {{ activeTasks[tid].status === 'running' ? '运行中' : activeTasks[tid].status === 'done' ? '完成' : '失败' }}
            </span>
            <span class="task-time">{{ fmtTime(activeTasks[tid].startedAt) }}</span>
          </div>
          <div class="task-meta">
            <span>源：<b>{{ taskMeta[tid]?.source || '—' }}</b></span>
            <span v-if="taskMeta[tid]?.mode">{{ taskMeta[tid].mode === 'full' ? '全量' : '增量' }}</span>
          </div>
          <div v-if="activeTasks[tid].status === 'running'" class="task-msg">处理中，请稍候…</div>
          <template v-else>
            <div class="task-msg">{{ taskResultText(activeTasks[tid]) }}</div>
            <div v-if="taskResultDetail(activeTasks[tid])" class="task-detail">{{ taskResultDetail(activeTasks[tid]) }}</div>
            <div v-if="activeTasks[tid].status === 'failed'" class="task-fail">{{ activeTasks[tid].message }}</div>
          </template>
        </div>
      </div>
    </template>

    <!-- 任务完成/失败 toast 提示 -->
    <transition name="toast">
      <div v-if="toast" class="toast" :class="toast.status">
        <div class="toast-head">
          <span class="toast-title">{{ toast.typeLabel }} · {{ toast.statusLabel }}</span>
          <button class="toast-close" @click="toast = null">×</button>
        </div>
        <div class="toast-text">{{ toast.text }}</div>
        <div v-if="toast.detail" class="toast-detail">{{ toast.detail }}</div>
      </div>
    </transition>
  </div>
</template>

<style scoped>
.lead { color: var(--text-2); font-size: 14px; margin: -8px 0 16px; }

.grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(360px, 1fr)); gap: 16px; }

.card { background: #fff; border: 1px solid var(--border); border-radius: 14px; padding: 16px; box-shadow: var(--shadow); }
.card-head { display: flex; align-items: center; justify-content: space-between; margin-bottom: 10px; }
.head-left { display: flex; align-items: center; gap: 8px; }
.src-name { font-weight: 800; font-size: 16px; }
.chip.pri.primary { background: var(--primary-soft); color: var(--primary-dark); }
.chip.pri.backup { background: #f0f0f0; color: var(--text-2); }

.card-meta { display: flex; flex-wrap: wrap; gap: 12px; font-size: 13px; color: var(--text-2); margin-bottom: 12px; }
.card-meta b { color: var(--text); }

.panel { border: 1px solid var(--border); border-radius: 10px; padding: 12px; margin-bottom: 12px; background: var(--bg); }
.panel-title { font-size: 13px; font-weight: 700; color: var(--primary-dark); margin-bottom: 8px; }
.row-inputs { display: flex; gap: 10px; flex-wrap: wrap; margin-bottom: 10px; }
.row-inputs label { display: flex; flex-direction: column; font-size: 12px; color: var(--text-2); gap: 4px; }
.row-inputs select, .row-inputs input {
  border: 1px solid var(--border); border-radius: 7px; padding: 5px 8px;
  font-size: 13px; background: #fff; color: var(--text); min-width: 90px;
}
.row-inputs input[type='number'] { min-width: 70px; }

/* 开关 */
.switch { position: relative; display: inline-block; width: 44px; height: 24px; }
.switch input { opacity: 0; width: 0; height: 0; }
.slider { position: absolute; inset: 0; background: #d9d2ca; border-radius: 999px; transition: 0.2s; cursor: pointer; }
.slider::before { content: ''; position: absolute; width: 18px; height: 18px; left: 3px; top: 3px; background: #fff; border-radius: 50%; transition: 0.2s; }
.switch input:checked + .slider { background: var(--primary); }
.switch input:checked + .slider::before { transform: translateX(20px); }

/* 任务 */
.task-bar { display: flex; align-items: center; justify-content: space-between; gap: 12px; }
.task-bar .section-title { margin: 28px 0 14px; }
.task-bar .btn.sm { padding: 5px 12px; font-size: 13px; }
.task-list { display: flex; flex-direction: column; gap: 10px; }
.task { background: #fff; border: 1px solid var(--border); border-radius: 12px; padding: 12px 14px; }
.task-head { display: flex; align-items: center; gap: 10px; margin-bottom: 4px; }
.task-meta { display: flex; gap: 12px; font-size: 12px; color: var(--text-2); margin-bottom: 4px; }
.task-meta b { color: var(--text); }
.chip.sync { background: var(--primary-soft); color: var(--primary-dark); }
.chip.transfer { background: #eef6ff; color: #2b6cb0; }
.status { font-size: 13px; font-weight: 700; }
.status.running { color: #b8860b; }
.status.done { color: #0a7d3a; }
.status.failed { color: #e23; }
.task-time { margin-left: auto; font-size: 12px; color: var(--text-2); }
.task-msg { font-size: 14px; font-weight: 600; }
.task-detail { font-size: 13px; color: var(--text-2); margin-top: 2px; }
.task-fail { font-size: 13px; color: #e23; margin-top: 2px; }

/* 任务完成/失败 toast */
.toast {
  position: fixed;
  top: 76px;
  right: 20px;
  z-index: 999;
  background: #fff;
  border: 1px solid var(--border);
  border-left: 4px solid var(--primary);
  border-radius: 12px;
  padding: 12px 16px;
  min-width: 280px;
  max-width: 380px;
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
.toast-enter-active, .toast-leave-active { transition: all 0.25s; }
.toast-enter-from, .toast-leave-to { opacity: 0; transform: translateX(20px); }
</style>
