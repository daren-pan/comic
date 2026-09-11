<script setup lang="ts">
import { onMounted, ref } from 'vue'
import {
  getAdminSources,
  toggleAdminSource,
  startAdminSync,
  startAdminTransfer,
  startAdminInspect,
} from '../api'
import { useMessageStore } from '../stores/message'
import type { SourceInfo } from '../types'

// 每个源的采集/转存/巡检操作表单状态（独立参数）
interface SourceVM {
  info: SourceInfo
  syncMode: 'incremental' | 'full'
  syncSince: string   // 起始日期（yyyy-MM-dd 或空）
  syncLimit: string   // 数量（空=不限）
  transferSince: string
  transferUntil: string
  inspectSince: string
  inspectUntil: string
  running: boolean    // 是否正在触发（防重复点击）
}

const sources = ref<SourceVM[]>([])
const loaded = ref(false)
const error = ref('')

// 任务结果一律写入全局消息中心（顶栏 🔔 展开可见，离开本页也会继续跟踪到结束）
const msgStore = useMessageStore()

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
      inspectSince: '',
      inspectUntil: '',
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
    msgStore.trackTask(taskId, 'sync', vm.info.name, vm.syncMode)
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
    // 转存即「窗口内全部未转存页」，不传 limit（后端 None = 不限制）
    const body = {
      source: vm.info.name,
      since: vm.transferSince || undefined,
      until: vm.transferUntil || undefined,
    }
    const { taskId } = await startAdminTransfer(body)
    msgStore.trackTask(taskId, 'transfer', vm.info.name)
  } catch (e) {
    alert((e as Error).message || '触发懒转存失败')
  } finally {
    vm.running = false
  }
}

async function runInspect(vm: SourceVM) {
  if (vm.running) return
  vm.running = true
  try {
    // 巡检 = 转存（窗口内全部未转存页）+ 全表校验已转存对象、缺失则恢复
    const body = {
      source: vm.info.name,
      since: vm.inspectSince || undefined,
      until: vm.inspectUntil || undefined,
    }
    const { taskId } = await startAdminInspect(body)
    msgStore.trackTask(taskId, 'inspect', vm.info.name)
  } catch (e) {
    alert((e as Error).message || '触发失效巡检失败')
  } finally {
    vm.running = false
  }
}

onMounted(load)
</script>

<template>
  <div>
    <h2 class="section-title">采集管理</h2>
    <p class="lead">
      手动触发各数据源的采集 / 懒转存 / 失效巡检；关闭的源将拒绝触发采集。
      转存会把所选时间范围内的未转存页<b>全部转存</b>（起止留空=全部）；
      巡检在此基础上还会<b>全表校验</b>已转存对象是否还在、缺失则自动恢复。
      任务进度与结果见右上角 <b>🔔 消息</b>（含历史记录，执行完毕会有提示）。
    </p>

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
            <label>截止（含当天）
              <input v-model="vm.transferUntil" type="date" />
            </label>
          </div>
          <button class="btn ghost" :disabled="vm.running" @click="runTransfer(vm)">
            {{ vm.running ? '运行中…' : '触发转存' }}
          </button>
        </div>

        <!-- 失效巡检区 -->
        <div class="panel">
          <div class="panel-title">失效巡检</div>
          <div class="row-inputs">
            <label>起始
              <input v-model="vm.inspectSince" type="date" />
            </label>
            <label>截止（含当天）
              <input v-model="vm.inspectUntil" type="date" />
            </label>
          </div>
          <button class="btn ghost" :disabled="vm.running" @click="runInspect(vm)">
            {{ vm.running ? '运行中…' : '触发巡检' }}
          </button>
        </div>
      </div>
    </div>
  </div>
</template>

<style scoped>
.lead { color: var(--text-2); font-size: 14px; margin: -8px 0 16px; }
.lead b { color: var(--primary-dark); }

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
</style>
