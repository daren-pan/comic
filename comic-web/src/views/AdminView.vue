<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import {
  getAdminSources,
  toggleAdminSource,
  startAdminSync,
  startAdminTransfer,
  startAdminInspect,
  startAdminHealCovers,
} from '../api'
import { useMessageStore } from '../stores/message'
import type { SourceInfo } from '../types'

// 每个源的采集/转存操作表单状态（独立参数）
interface SourceVM {
  info: SourceInfo
  syncMode: 'incremental' | 'full'
  syncSince: string   // 起始日期（yyyy-MM-dd 或空）
  syncLimit: string   // 数量（空=不限）
  transferSince: string
  transferUntil: string
  running: boolean    // 是否正在触发（防重复点击）
}

const sources = ref<SourceVM[]>([])
const loaded = ref(false)
const error = ref('')

// 失效巡检与封面自愈都是**全库**动作（前者扫整张 page 表、后者扫整张 comic 表），
// 故都不放进各源卡片，统一在页面顶部各占一个面板
const inspectSince = ref('')
const inspectUntil = ref('')
const inspecting = ref(false)
const healing = ref(false)   // 全库封面自愈是否正在触发

// 任务结果一律写入全局消息中心（顶栏 🔔 展开可见，离开本页也会继续跟踪到结束）
const msgStore = useMessageStore()
const router = useRouter()

// 「采集/转存日志」入口：跳到独立的日志查询页（/#/admin/logs）
// 日志已落库（log_record 表），查询页支持按级别/源站/事件/作品/任务/时间/关键字筛，故不再需要弹窗轮询
function openLogs() {
  router.push('/admin/logs')
}

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

// 全库失效巡检：转存窗口内未转存页 + 全表校验已转存对象、缺失则恢复
async function runInspect() {
  if (inspecting.value) return
  inspecting.value = true
  try {
    const body = {
      since: inspectSince.value || undefined,
      until: inspectUntil.value || undefined,
    }
    const { taskId } = await startAdminInspect(body)
    msgStore.trackTask(taskId, 'inspect', '全库')
  } catch (e) {
    alert((e as Error).message || '触发失效巡检失败')
  } finally {
    inspecting.value = false
  }
}

// 全库封面自愈：只修封面（外链未落盘 → 重下；本地文件缺失 → 回源重抓），不转存正文页
async function runHealCovers() {
  if (healing.value) return
  healing.value = true
  try {
    const { taskId } = await startAdminHealCovers()
    msgStore.trackTask(taskId, 'heal', '全库')
  } catch (e) {
    alert((e as Error).message || '触发封面自愈失败')
  } finally {
    healing.value = false
  }
}

onMounted(load)
</script>

<template>
  <div>
    <!-- 标题行：右侧放「采集/转存日志」入口（跳转日志查询页） -->
    <div class="title-row">
      <h2 class="section-title">采集管理</h2>
      <button class="btn ghost" @click="openLogs">📄 采集/转存日志</button>
    </div>
    <p class="lead">
      手动触发各数据源的采集与懒转存；关闭的源将拒绝触发采集。
      转存会把所选时间范围内的未转存页<b>全部转存</b>（起止留空=全部）。
      顶部的<b>失效巡检</b>与<b>封面自愈</b>是两个<b>全库</b>动作，不针对单个源。
      任务进度与结果见右上角 <b>🔔 消息</b>（含历史记录，执行完毕会有提示）。
    </p>

    <div v-if="error" class="empty" style="color:#e23">{{ error }}</div>
    <div v-else-if="!loaded" class="empty">加载数据源中…</div>

    <template v-else>
      <!-- 全库维护：失效巡检 / 封面自愈都是「全库」动作，故不放各源卡片内，页面顶部各占一个面板 -->
      <div class="maint-row">
        <!-- 失效巡检：全库动作（扫描整张 page 表） -->
        <div class="maintenance">
          <div class="maint-head">
            <span class="maint-title">失效巡检</span>
            <span class="maint-tag">全库</span>
          </div>
          <p class="maint-desc">
            把所选时间范围内的未转存页<b>全部转存</b>，并<b>全表校验</b>已转存对象是否还在、
            缺失则自动恢复（起止留空 = 全库）。与「触发转存」的唯一区别就是这一步校验。
          </p>
          <div class="row-inputs">
            <label>起始
              <input v-model="inspectSince" type="date" />
            </label>
            <label>截止（含当天）
              <input v-model="inspectUntil" type="date" />
            </label>
          </div>
          <button class="btn ghost" :disabled="inspecting" @click="runInspect">
            {{ inspecting ? '运行中…' : '触发巡检' }}
          </button>
        </div>

        <!-- 封面自愈：全库动作（扫描整张 comic 表），只修封面、不转存正文页 -->
        <div class="maintenance">
          <div class="maint-head">
            <span class="maint-title">封面自愈</span>
            <span class="maint-tag cover">全库</span>
          </div>
          <p class="maint-desc">
            逐部检查封面：外链未落盘的<b>重新下载</b>，本地文件缺失的<b>回源重抓</b>，健康的跳过。
            与「触发转存」的区别是它<b>只修封面、不转存正文页</b>（转存只自愈所点那个源）。
          </p>
          <button class="btn ghost" :disabled="healing" @click="runHealCovers">
            {{ healing ? '运行中…' : '触发全库自愈' }}
          </button>
        </div>
      </div>

      <!-- 数据源卡片 -->
      <div class="grid">
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
        </div>
      </div>
    </template>

  </div>
</template>

<style scoped>
/* 标题行：标题 + 右侧「采集/转存日志」入口（外层间距由本行统一控制，故标题自身 margin 归零） */
.title-row {
  display: flex;
  align-items: center;
  gap: 12px;
  flex-wrap: wrap;
  margin: 28px 0 6px;
}
.title-row .section-title { margin: 0; }
.title-row .btn { margin-left: auto; }   /* 按钮靠右，与标题同一行 */

.lead { color: var(--text-2); font-size: 14px; margin: 0 0 16px; }
.lead b { color: var(--primary-dark); }

.grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(360px, 1fr)); gap: 16px; }

/* 全库维护区：失效巡检 / 封面自愈 两块并排（窄屏自动堆叠） */
.maint-row {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(360px, 1fr));
  gap: 16px;
  margin-bottom: 16px;
}

/* 全库维护面板（不随源卡片复制） */
.maintenance {
  background: #fff; border: 1px solid var(--border); border-radius: 14px;
  padding: 16px; box-shadow: var(--shadow);
}
.maint-head { display: flex; align-items: center; gap: 8px; margin-bottom: 6px; }
.maint-title { font-weight: 800; font-size: 16px; }
.maint-tag { font-size: 12px; font-weight: 700; padding: 1px 8px; border-radius: 999px; background: #eef7ec; color: #2f6d1f; }
.maint-tag.cover { background: #fff4e5; color: #a15c00; }
.maint-desc { color: var(--text-2); font-size: 13px; margin: 0 0 12px; }
.maint-desc b { color: var(--primary-dark); }

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
