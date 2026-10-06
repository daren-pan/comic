<script setup lang="ts">
/**
 * 定时任务页（`/#/admin/schedule`）。
 *
 * 用 **5 段 cron**（`分 时 日 月 周`）决定什么时候跑，对选中的数据源各执行一次采集
 * （`mode` 增量/全量、`limit`/`since` 与「触发采集」是同一套参数）。
 *
 * ⚠️ **采集跑在独立进程 `comic-scheduler` 里**（2026-10-06 从 api 进程搬出）：
 * 本页保存的配置写进运行时数据目录的 `schedule.json`，执行器每 5s 看一次表；
 * 「立即执行一次」也只是写一个触发文件，执行器看到才跑 —— 所以**本页拿不到任务号**，
 * 只能过几秒刷状态看结果；执行器没起来时配置照样存得下，但**不会有人跑**，
 * 故状态面板专门显示「执行器：在线 / 离线」（靠心跳判定）。
 *
 * ⚠️ 另外三件容易误解的事，页面上也写明：
 * 1. **参数即准入** —— 定时任务**不看**采集管理页那张数据源开关；
 * 2. `sources` 留空 = 全部「**代码里默认启用**」的源（`mangadex` 因 AUP 非商用默认关闭，
 *    要采集必须在这里点名）；
 * 3. **错过不补** —— 到点时执行器没在跑（或已过宽限窗口）就跳过这一轮。
 */
import { ref } from 'vue'
import {
  getAdminSchedule,
  getAdminSources,
  runAdminScheduleNow,
  saveAdminSchedule,
} from '../../api'
import type { AdminScheduleConfig, AdminScheduleStatus, PickerOption, SourceInfo } from '../../types'
import { useMessageStore } from '../../stores/message'
import { onLoad, onUnload } from '@dcloudio/uni-app'
import { setRoute } from '../../utils/router'
import { requireRole } from '../../utils/guard'
import { showAlert, showConfirm } from '../../utils/ui'

const msgStore = useMessageStore()
import Layout from '../../components/Layout.vue'
import AdminTabs from '../../components/AdminTabs.vue'
import DateInput from '../../components/DateInput.vue'
import Picker from '../../components/Picker.vue'

// 门卫通过前不渲染页面主体（等价 comic-web 守卫拦住时整页不出现）
const ready = ref(false)
const error = ref('')
const saving = ref(false)
const starting = ref(false)

const status = ref<AdminScheduleStatus | null>(null)
const sources = ref<SourceInfo[]>([])

// 表单：从后端配置拷一份，改完点「保存」才落盘（不自动保存，避免边填边生效）
const form = ref({
  enabled: false,
  cron: '0 3 * * *',
  action: 'sync' as 'sync' | 'inspect',
  sources: [] as string[],
  mode: 'incremental' as 'incremental' | 'full',
  limit: '' as string,
  since: '' as string,
})

// 采集模式下拉：小程序没有 <select>，统一走 Picker（见 components/Picker.vue）
const modeOptions: PickerOption[] = [
  { value: 'incremental', label: '增量' },
  { value: 'full', label: '全量' },
]

// 动作下拉：采集（逐源跑一轮）或失效巡检（转存 + 全表校验 + 恢复）
const actionOptions: PickerOption[] = [
  { value: 'sync', label: '采集' },
  { value: 'inspect', label: '失效巡检' },
]

function onAction(v: string | number) {
  form.value.action = v === 'inspect' ? 'inspect' : 'sync'
}

// cron 预设：手机上手敲 5 段太费劲，给几个常用的一键填入（表达式照抄后端语法）
const cronPresets: { label: string; expr: string }[] = [
  { label: '每 15 分钟', expr: '*/15 * * * *' },
  { label: '每小时', expr: '0 * * * *' },
  { label: '每 6 小时', expr: '0 */6 * * *' },
  { label: '每天 03:00', expr: '0 3 * * *' },
  { label: '每周一 03:00', expr: '0 3 * * 1' },
]

function usePreset(expr: string) {
  form.value.cron = expr
}

/** cron 形状自检：必须 5 段且每段非空。范围/步长等语义由后端 `parse_cron` 判（非法返 400）。 */
function cronLooksValid(expr: string): boolean {
  const parts = expr.trim().split(/\s+/)
  return parts.length === 5 && parts.every((p) => p.length > 0)
}

// 「立即执行」提交后的状态轮询（执行器在另一个进程里，拿不到任务号，只能看状态）
let pollTimer: ReturnType<typeof setInterval> | null = null

function stopPolling() {
  if (pollTimer !== null) {
    clearInterval(pollTimer)
    pollTimer = null
  }
}

function onMode(v: string | number) {
  form.value.mode = v === 'full' ? 'full' : 'incremental'
}

function isPicked(name: string) {
  return form.value.sources.includes(name)
}

function toggleSource(name: string) {
  const list = form.value.sources
  const i = list.indexOf(name)
  if (i >= 0) list.splice(i, 1)
  else list.push(name)
}

function applyStatus(s: AdminScheduleStatus) {
  status.value = s
  form.value = {
    enabled: s.config.enabled,
    cron: s.config.cron,
    action: s.config.action === 'inspect' ? 'inspect' : 'sync',
    sources: [...s.config.sources],
    mode: s.config.mode,
    limit: s.config.limit === null || s.config.limit === undefined ? '' : String(s.config.limit),
    since: s.config.since ?? '',
  }
}

function fmt(iso: string | null): string {
  if (!iso) return '—'
  const d = new Date(iso)
  const pad = (n: number) => String(n).padStart(2, '0')
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())} ${pad(d.getHours())}:${pad(d.getMinutes())}`
}

function statusText(): string {
  const s = status.value
  if (!s) return '—'
  if (s.running || s.lastStatus === 'running') return '运行中'
  if (s.lastStatus === 'done') return '完成'
  if (s.lastStatus === 'failed') return '部分/全部失败'
  return '尚未执行'
}

/** 执行器（独立进程 `comic-scheduler`）在不在 —— 它不在时"配了也不会跑"，必须显眼。 */
function executorText(): string {
  const s = status.value
  if (!s) return '—'
  if (!s.executorAlive) return '离线（配置能存，但没人跑）'
  return s.executorPid ? `在线（pid ${s.executorPid}）` : '在线'
}

/** 「起始日期」的含义随动作变：采集 = 时间窗下界；巡检 = **转存**窗口下界（校验始终全表）。 */
function sinceHint(): string {
  return form.value.action === 'inspect'
    ? '巡检时它是「转存」窗口的下界（全表校验不受它影响）；留空 = 不限制'
    : '时间窗下界（可选）；留空 = 按源自身水位'
}

/** 「数据源」的含义也随动作变：采集 = 逐源跑；巡检 = 只认一个源，多选/留空都算全库。 */
function sourceHint(): string {
  if (form.value.action === 'inspect') {
    return '巡检只认一个源：只勾一个 = 只巡检它（同时限定转存范围）；勾多个或留空 = 全库全源'
  }
  const names = status.value?.sources.join('、') || '—'
  return `留空 = 全部默认启用的源，即 ${names}；「开关已关」只影响采集管理页的手动触发，不影响这里。`
}

async function load() {
  error.value = ''
  try {
    const [s, list] = await Promise.all([
      getAdminSchedule(),
      getAdminSources().catch(() => [] as SourceInfo[]),
    ])
    sources.value = list
    applyStatus(s)
  } catch (e) {
    error.value = (e as Error).message || '加载定时任务配置失败'
  }
}

async function save() {
  if (saving.value) return
  const cron = form.value.cron.trim()
  if (!cronLooksValid(cron)) {
    showAlert('cron 要写 5 段：分 时 日 月 周，例如 0 3 * * *（每天 03:00）')
    return
  }
  if (form.value.limit && !(Number(form.value.limit) >= 1)) {
    showAlert('数量上限要么留空（不限），要么填 >= 1 的整数')
    return
  }
  saving.value = true
  try {
    const body: AdminScheduleConfig = {
      enabled: form.value.enabled,
      cron: cron.replace(/\s+/g, ' '),
      action: form.value.action,
      sources: [...form.value.sources],
      mode: form.value.mode,
      limit: form.value.limit ? Number(form.value.limit) : null,
      since: form.value.since || null,
    }
    // 返回值才是**实际生效**的配置：未注册的源名会被后端丢弃
    applyStatus(await saveAdminSchedule(body))
    showAlert('已保存')
  } catch (e) {
    // 后端 400 的消息就是 cron 的具体错因（带段名），原样展示最有帮助
    showAlert((e as Error).message || '保存失败')
  } finally {
    saving.value = false
  }
}

async function runNow() {
  if (starting.value) return
  if (!(await showConfirm('请求立即对选中的数据源跑一轮采集？', '立即执行'))) return
  starting.value = true
  try {
    // ⚠️ 采集在**独立进程**里跑：这里只是把请求写成一个文件，执行器下一个 tick（≤5s）看到才跑。
    //    所以拿不到 taskId，只能过几秒刷状态看「运行中 / 最近执行」。
    const r = await runAdminScheduleNow()
    if (!r || !r.requested) {
      showAlert('请求没能提交，稍后再试')
      return
    }
    if (status.value && !status.value.executorAlive) {
      showAlert('请求已提交，但执行器当前不在线 —— 它起来后会自动补跑这一轮')
    } else {
      showAlert('已请求，执行器几秒内开始（下方状态会自动刷新）')
    }
    pollAfterRequest()
  } catch (e) {
    showAlert((e as Error).message || '触发失败')
  } finally {
    starting.value = false
  }
}

/**
 * 提交后跟一段状态：执行器在另一个进程，没有任务号可跟踪，只能轮询。
 * 看到跑起来就多跟两次让它落到完成；否则约 20~40s 后停 —— 长任务不必一直占着定时器。
 */
function pollAfterRequest() {
  stopPolling()
  let times = 0
  pollTimer = setInterval(async () => {
    times += 1
    await load()
    // 顺带刷新消息中心：这一轮是**另一个进程**跑的、也没有任务号可跟踪，它出现/完成只能靠
    // 服务端（消息中心会把"正在跑的任务"临时并进列表，跑完再补一条结果消息）
    msgStore.refresh()
    const running = status.value?.running
    if (times >= 8 || (!running && times >= 4)) stopPolling()
  }, 5000)
}

onLoad(async (options) => {
  // uni 页面生命周期：登记该页对应的 web 路径（替代 vue-router 的路由状态）
  setRoute('/admin/schedule', options ?? {})
  // 门卫：未登录 / 角色不够 → 跳走并终止本页加载（管理台与日志页同级门槛）
  if (!(await requireRole(false, '/admin/schedule'))) return
  ready.value = true
  load()
})

// 离开页面就停掉状态轮询（否则定时器会一直跑着调接口）
onUnload(stopPolling)
</script>

<template>
  <Layout>
    <view v-if="ready">
      <!-- 管理台同一栏的三个选项卡（采集管理 / 定时任务 / 运行日志）—— 点选项切换，
           "返回采集管理"就是左边的第一个选项，不再单独放返回按钮（见 components/AdminTabs.vue） -->
      <view class="title-row">
        <AdminTabs current="schedule" />
      </view>
      <view class="lead u-p">
        用 <text class="u-b">cron 表达式</text>决定什么时候跑（<text class="u-b">分 时 日 月 周</text> 五段）：
        <text class="u-code">0 3 * * *</text> = 每天 03:00，<text class="u-code">*/15 * * * *</text> = 每隔 15 分钟，
        <text class="u-code">0 3 * * 1</text> = 每周一 03:00。每轮的参数与「触发采集」同一套。
        <text class="u-b">参数即准入</text>：这里<text class="u-b">不看</text>采集管理页的源开关；数据源留空 = 全部「代码里默认启用」的源。
        到点时执行器没在跑就跳过这一轮（<text class="u-b">错过不补</text>），要补就跑「立即执行一次」。
        采集由<text class="u-b">独立进程</text>（comic-scheduler）执行：本页只管配置，它在不在看下面「执行器」一行。
      </view>

      <!-- cron 表达式非法（配置文件被手改坏）时的明确提示，不静默 -->
      <view v-if="status && status.cronError" class="empty" style="color:#e23">
        cron 表达式有问题：{{ status.cronError }}（本轮不会触发，改好并保存即恢复）
      </view>

      <view v-if="error" class="empty" style="color:#e23">{{ error }}</view>
      <view v-else-if="!status" class="empty">加载中…</view>

      <template v-else>
        <!-- 运行态：不参与保存，纯展示 -->
        <view class="panel">
          <view class="panel-head">
            <text class="panel-title u-span">运行状态</text>
            <text class="badge u-span" :class="status.lastStatus || 'idle'">{{ statusText() }}</text>
          </view>
          <view class="kv u-p">
            <text class="k u-label">下次执行</text><text class="v u-code">{{ fmt(status.nextRunAt) }}</text>
            <text class="k u-label">最近执行</text><text class="v u-code">{{ fmt(status.lastRunAt) }}</text>
            <text class="k u-label">本轮源</text><text class="v u-code">{{ status.sources.join('、') || '—' }}</text>
            <text class="k u-label">结果</text><text class="v u-code">{{ status.lastMessage || '—' }}</text>
            <text class="k u-label">任务号</text><text class="v u-code">{{ status.lastTaskId || '—' }}</text>
            <text class="k u-label">执行器</text>
            <text class="v u-code" :style="{ color: status.executorAlive ? '#1f7a44' : '#c0392b' }">{{ executorText() }}</text>
            <text class="k u-label">执行器心跳</text><text class="v u-code">{{ fmt(status.heartbeatAt) }}</text>
            <text class="k u-label">服务器时间</text><text class="v u-code">{{ fmt(status.serverTime) }}</text>
          </view>
        </view>

        <!-- 配置表单 -->
        <view class="panel">
          <view class="panel-head">
            <text class="panel-title u-span">任务配置</text>
          </view>

          <view class="form-row">
            <text class="u-label">启用</text>
            <switch class="sw" :checked="form.enabled" @change="form.enabled = !form.enabled" />
            <text class="hint u-span">关掉后定时器不再触发（配置保留）</text>
          </view>

          <view class="form-row">
            <text class="u-label">动作</text>
            <Picker class="u-select" :model-value="form.action" :options="actionOptions" @update:model-value="onAction" />
            <text class="hint u-span">
              {{ form.action === 'inspect'
                ? '失效巡检：转存未转存页 + 全表校验 + 恢复丢失（不含「全库封面自愈」，那步在手动巡检里）'
                : '采集：对选中的数据源各跑一轮' }}
            </text>
          </view>

          <view class="form-row form-row-col">
            <text class="u-label">cron 表达式</text>
            <input class="u-input w-cron mono" v-model="form.cron" placeholder="0 3 * * *" />
            <view class="chips chips-tight">
              <view
                v-for="p in cronPresets"
                :key="p.expr"
                class="chip"
                :class="{ on: form.cron.trim().replace(/\s+/g, ' ') === p.expr }"
                @click="usePreset(p.expr)"
              >
                <text class="chip-name">{{ p.label }}</text>
              </view>
            </view>
            <text class="hint u-span">
              五段：<text class="u-code">分 时 日 月 周</text>；支持 <text class="u-code">*</text> /
              <text class="u-code">*/N</text> / <text class="u-code">a-b</text> /
              <text class="u-code">a-b/N</text> / 逗号列表。
              日与周同时写具体值时是「或」（如 <text class="u-code">0 3 1 * 1</text> = 每月 1 号或每周一）。
              范围/步长由后端校验，非法会给出是哪一段错了。
            </text>
          </view>

          <view v-if="form.action === 'sync'" class="form-row">
            <text class="u-label">采集模式</text>
            <Picker class="u-select" :model-value="form.mode" :options="modeOptions" @update:model-value="onMode" />
            <text class="hint u-span">全量 = 扫榜单全部；增量 = 只取新更新的</text>
          </view>

          <view v-if="form.action === 'sync'" class="form-row">
            <text class="u-label">数量上限</text>
            <input class="u-input w-time" v-model="form.limit" type="number" placeholder="不限" />
            <text class="hint u-span">受控样本数（与「触发采集」的 limit 同义）；留空 = 不限</text>
          </view>

          <view class="form-row">
            <text class="u-label">起始日期</text>
            <DateInput :model-value="form.since" @update:model-value="form.since = $event" />
            <text class="hint u-span">{{ sinceHint() }}</text>
          </view>

          <view class="form-row form-row-col">
            <text class="u-label">数据源</text>
            <view class="chips">
              <view
                v-for="s in sources"
                :key="s.name"
                class="chip"
                :class="{ on: isPicked(s.name) }"
                @click="toggleSource(s.name)"
              >
                <text class="chip-name">{{ s.name }}</text>
                <text v-if="!s.enabled" class="chip-off">（开关已关）</text>
              </view>
            </view>
            <text class="hint u-span">{{ sourceHint() }}</text>
          </view>

          <view class="actions">
            <button class="btn u-button" :disabled="saving" @click="save">{{ saving ? '保存中…' : '保存配置' }}</button>
            <button class="btn ghost u-button" :disabled="starting" @click="runNow">
              {{ starting ? '触发中…' : '立即执行一次' }}
            </button>
          </view>
        </view>
      </template>
    </view>
  </Layout>
</template>

<style scoped>
/* 顶部那一栏：管理台三个选项卡（采集管理 / 定时任务 / 运行日志，见 components/AdminTabs.vue）——
   原来这里是"标题 + ← 返回采集管理"，返回已由选项卡的第一个选项取代 */
.title-row {
  display: flex;
  align-items: center;
  gap: 12px;
  flex-wrap: wrap;
  margin: 28px 0 6px;
}

/* 面板 */
.panel {
  margin: 14px 0;
  padding: 14px 16px;
  background: #fff;
  border: 1px solid #e8e4dc;
  border-radius: 10px;
}
.panel-head {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-bottom: 10px;
}
.panel-title { font-weight: 600; }
.badge {
  padding: 1px 8px;
  border-radius: 10px;
  font-size: 12px;
  background: #efeae1;
  color: #6b6257;
}
.badge.running { background: #e6f0ff; color: #2b5fd9; }
.badge.done { background: #e7f5ec; color: #1f7a44; }
.badge.failed { background: #fdeaea; color: #c0392b; }

/* 键值展示 */
.kv {
  display: flex;
  flex-wrap: wrap;
  gap: 6px 10px;
}
.kv .k { color: #8a8175; }
.kv .v { margin-right: 14px; word-break: break-all; }

/* 表单 */
.form-row {
  display: flex;
  align-items: center;
  gap: 10px;
  flex-wrap: wrap;
  padding: 8px 0;
  border-top: 1px dashed #f0ece5;
}
.form-row:first-of-type { border-top: none; }
.form-row-col { flex-direction: column; align-items: flex-start; }
.form-row .u-label { min-width: 72px; }
.w-time { width: 110px; }
/* cron 表达式要比时间宽些（要放得下五位星号那种写法）；等宽字体便于对齐五段 */
.w-cron { width: 210px; font-family: ui-monospace, Menlo, Consolas, monospace; }
.chips-tight { margin-top: 2px; }
.hint { color: #8a8175; font-size: 12px; }
.sw { transform: scale(0.85); }

/* 数据源多选：点一下切换（避免引入自定义组件 + v-model 的多端坑） */
.chips {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
}
.chip {
  display: flex;
  align-items: center;
  padding: 5px 12px;
  border: 1px solid #ddd6ca;
  border-radius: 16px;
  background: #faf8f5;
  color: #4a4238;
}
.chip.on {
  background: #4a4238;
  border-color: #4a4238;
  color: #fff;
}
.chip-off { margin-left: 4px; font-size: 11px; opacity: 0.7; }

.actions {
  display: flex;
  gap: 10px;
  margin-top: 14px;
}
</style>
