<script setup lang="ts">
import { ref } from 'vue'
import {
  getAdminSources,
  toggleAdminSource,
  startAdminSync,
  startAdminInspect,
  startAdminHealCovers,
} from '../../api'
import { useMessageStore } from '../../stores/message'
import type { PickerOption, SourceInfo } from '../../types'
import { onLoad } from '@dcloudio/uni-app'
import { setRoute, useRouter } from '../../utils/router'
import { requireRole } from '../../utils/guard'
import Layout from '../../components/Layout.vue'
import DateInput from '../../components/DateInput.vue'
import Picker from '../../components/Picker.vue'

// 每个源的采集操作表单状态（独立参数）
interface SourceVM {
  info: SourceInfo
  syncMode: 'incremental' | 'full'
  syncSince: string   // 起始日期（yyyy-MM-dd 或空）
  syncLimit: string   // 数量（空=不限）
  running: boolean    // 是否正在触发（防重复点击）
}

// 采集模式下拉：小程序没有 <select>，统一走 Picker（见 components/Picker.vue）
const syncModeOptions: PickerOption[] = [
  { value: 'incremental', label: '增量' },
  { value: 'full', label: '全量' },
]

function onSyncMode(vm: SourceVM, mode: string | number) {
  vm.syncMode = mode === 'full' ? 'full' : 'incremental'
}

const sources = ref<SourceVM[]>([])
const loaded = ref(false)
const error = ref('')
// 门卫通过前不渲染页面主体（等价 comic-web 守卫拦住时整页不出现）
const ready = ref(false)

// 失效巡检是**全库**动作（扫描整张 page 表），故不放进各源卡片，页面顶部独占一个面板；
// 封面自愈面板则按**指定作品**（名称/ID）强制刷新封面。
const inspectSince = ref('')
const inspectUntil = ref('')
const inspecting = ref(false)
const healing = ref(false)       // 按作品封面自愈是否正在触发
const healKeyword = ref('')      // 漫画名称或 ID（可多个，逗号/空格/换行分隔）—— 不允许留空

// 任务结果一律写入全局消息中心（顶栏 🔔 展开可见，离开本页也会继续跟踪到结束）
const msgStore = useMessageStore()
const router = useRouter()

// 「运行日志」入口：跳到独立的日志查询页（/#/admin/logs）
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

// 全库失效巡检：转存窗口内未转存页 + 全表校验已转存对象、缺失则恢复 + 全库封面自愈
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

// 按作品封面自愈：填漫画名称或 ID（可多个）→ **强制**回源重抓封面并覆盖（修「文件在但内容错」的封面）
async function runHealCovers() {
  if (healing.value) return
  const keyword = healKeyword.value.trim()
  if (!keyword) {
    alert('请填写漫画名称或 ID（可多个，用逗号/空格/换行分隔）')
    return
  }
  healing.value = true
  try {
    const { taskId } = await startAdminHealCovers({ keyword })
    msgStore.trackTask(taskId, 'heal', keyword)
  } catch (e) {
    alert((e as Error).message || '触发封面自愈失败')
  } finally {
    healing.value = false
  }
}

onLoad(async (options) => {
  // uni 页面生命周期：登记该页对应的 web 路径（替代 vue-router 的路由状态）
  setRoute('/admin', options ?? {})
  // 门卫：未登录 / 角色不够 → 跳走并终止本页加载（等价 comic-web 的 beforeEnter: requireRole(false)）
  if (!(await requireRole(false, '/admin'))) return
  ready.value = true
  void load()
})

</script>

<template>
  <Layout>
    <view v-if="ready">
      <!-- 标题行：右侧放「运行日志」入口（跳转日志查询页） -->
      <view class="title-row">
        <view class="section-title">采集管理</view>
        <button class="btn ghost u-button" @click="openLogs">📄 运行日志</button>
      </view>
      <view class="lead u-p">
        手动触发各数据源的采集；关闭的源将拒绝触发采集。
        顶部的<text class="u-b">失效巡检</text>是<text class="u-b">全库维护的唯一入口</text>（转存未转存页 + 全表校验恢复 + 封面自愈）；
        <text class="u-b">封面自愈</text>按<text class="u-b">指定作品</text>（名称/ID）强制刷新。
        任务进度与结果见右上角 <text class="u-b">🔔 消息</text>（含历史记录，执行完毕会有提示）。
      </view>

      <view v-if="error" class="empty" style="color:#e23">{{ error }}</view>
      <view v-else-if="!loaded" class="empty">加载数据源中…</view>

      <template v-else>
        <!-- 全库维护区：失效巡检（全库）+ 封面自愈（按指定作品），不放各源卡片内 -->
        <view class="maint-row">
          <!-- 失效巡检：全库动作（扫描整张 page 表） -->
          <view class="maintenance">
            <view class="maint-head">
              <text class="maint-title u-span">失效巡检</text>
              <text class="maint-tag u-span">全库</text>
            </view>
            <view class="maint-desc u-p">
              <text class="u-b">全库维护的唯一入口</text>：把所选时间范围内的未转存页<text class="u-b">全部转存</text>、
              <text class="u-b">全表校验</text>已转存对象是否还在（缺失自动恢复），并做<text class="u-b">全库封面自愈</text>
              （起止留空 = 全库）。
            </view>
            <view class="row-inputs">
              <view class="u-label">起始
                <DateInput
                  :model-value="inspectSince"
                  @update:model-value="inspectSince = $event"
                />
              </view>
              <view class="u-label">截止（含当天）
                <DateInput
                  :model-value="inspectUntil"
                  @update:model-value="inspectUntil = $event"
                />
              </view>
            </view>
            <button class="btn ghost u-button" :disabled="inspecting" @click="runInspect">
              {{ inspecting ? '运行中…' : '触发巡检' }}
            </button>
          </view>

          <!-- 封面自愈：按指定作品（名称/ID）强制刷新封面，只修封面、不转存正文页 -->
          <view class="maintenance">
            <view class="maint-head">
              <text class="maint-title u-span">封面自愈</text>
              <text class="maint-tag cover u-span">指定作品</text>
            </view>
            <view class="maint-desc u-p">
              填漫画名称或 ID（可多个）→ <text class="u-b">强制</text>回源重抓封面并覆盖，专治<text class="u-b">「封面文件在、但内容是错的」</text>
              （普通自愈只看文件在不在，永远修不到错图）。只修封面、<text class="u-b">不转存正文页</text>。
            </view>
            <view class="heal-field u-label">
              漫画名称或 ID（可多个，逗号 / 空格 / 换行分隔）
              <textarea class="u-textarea" v-model="healKeyword" rows="2" placeholder="如：电锯人, 17, 海贼王"></textarea>
            </view>
            <button class="btn ghost u-button" :disabled="healing" @click="runHealCovers">
              {{ healing ? '运行中…' : '触发封面自愈' }}
            </button>
          </view>
        </view>

        <!-- 数据源卡片 -->
        <view class="grid">
          <view v-for="vm in sources" :key="vm.info.name" class="card">
            <view class="card-head">
              <view class="head-left">
                <text class="src-name u-span">{{ vm.info.name }}</text>
                <text class="chip pri u-span" :class="vm.info.priority">{{ vm.info.priority === 'primary' ? '主源' : '备源' }}</text>
              </view>
              <!-- 开关：**不能用原生 checkbox** —— uni 的 <input> 有 type 白名单（不含 checkbox，
                   会被抹成 text），且 <label> 已被映射成 view、失去「点容器激活内部控件」的能力。
                   所以这里不依赖任何原生控件：纯 view + 显式点击，选中态走类名（见 <style>）。 -->
              <view
                class="switch"
                :class="{ on: vm.info.enabled }"
                :title="vm.info.enabled ? '点击关闭采集' : '点击开启采集'"
                @click="toggleSource(vm)"
              >
                <text class="slider u-span"></text>
              </view>
            </view>

            <view class="card-meta">
              <text class="u-span">库内 <text class="u-b">{{ vm.info.comicCount }}</text> 部</text>
              <text class="u-span">间隔 <text class="u-b">{{ fmtInterval(vm.info.interval) }}</text></text>
              <text class="u-span">上次同步 <text class="u-b">{{ fmtTime(vm.info.lastSync) }}</text></text>
            </view>

            <!-- 采集区 -->
            <view class="panel">
              <view class="panel-title">采集</view>
              <view class="row-inputs">
                <view class="u-label">模式
                  <Picker
                    class="u-select"
                    :model-value="vm.syncMode"
                    :options="syncModeOptions"
                    @update:model-value="onSyncMode(vm, $event)"
                  />
                </view>
                <view class="u-label">起始日期
                  <DateInput
                    :model-value="vm.syncSince"
                    @update:model-value="vm.syncSince = $event"
                  />
                </view>
                <view class="u-label">数量
                  <input class="u-input" v-model="vm.syncLimit" type="number" min="1" placeholder="不限" />
                </view>
              </view>
              <button class="btn u-button" :disabled="vm.running || !vm.info.enabled" @click="runSync(vm)">
                {{ vm.running ? '运行中…' : '触发采集' }}
              </button>
            </view>
          </view>
        </view>
      </template>

    </view>
  </Layout>
</template>

<style scoped>
/* 标题行：标题 + 右侧「运行日志」入口（外层间距由本行统一控制，故标题自身 margin 归零） */
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
.lead .u-b { color: var(--primary-dark); }

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
  background: var(--card); border: 1px solid var(--border); border-radius: 14px;
  padding: 16px; box-shadow: var(--shadow);
}
.maint-head { display: flex; align-items: center; gap: 8px; margin-bottom: 6px; }
.maint-title { font-weight: 800; font-size: 16px; }
.maint-tag { font-size: 12px; font-weight: 700; padding: 1px 8px; border-radius: 999px; background: #eef7ec; color: #2f6d1f; }
.maint-tag.cover { background: #fff4e5; color: #a15c00; }
.maint-desc { color: var(--text-2); font-size: 13px; margin: 0 0 12px; }
.maint-desc .u-b { color: var(--primary-dark); }

/* 封面自愈：漫画名称/ID 输入（可多个，支持换行） */
.heal-field { display: flex; flex-direction: column; font-size: 12px; color: var(--text-2); gap: 4px; margin-bottom: 10px; }
.heal-field .u-textarea {
  border: 1px solid var(--border); border-radius: 7px; padding: 6px 8px;
  font-size: 13px; background: var(--card); color: var(--text); font-family: inherit;
  width: 100%; box-sizing: border-box; resize: vertical;
}

.card { background: var(--card); border: 1px solid var(--border); border-radius: 14px; padding: 16px; box-shadow: var(--shadow); }
.card-head { display: flex; align-items: center; justify-content: space-between; margin-bottom: 10px; }
.head-left { display: flex; align-items: center; gap: 8px; }
.src-name { font-weight: 800; font-size: 16px; }
.chip.pri.primary { background: var(--primary-soft); color: var(--primary-dark); }
.chip.pri.backup { background: var(--mute); color: var(--text-2); }

.card-meta { display: flex; flex-wrap: wrap; gap: 12px; font-size: 13px; color: var(--text-2); margin-bottom: 12px; }
.card-meta .u-b { color: var(--text); }

.panel { border: 1px solid var(--border); border-radius: 10px; padding: 12px; margin-bottom: 12px; background: var(--bg); }
.panel-title { font-size: 13px; font-weight: 700; color: var(--primary-dark); margin-bottom: 8px; }
.row-inputs { display: flex; gap: 10px; flex-wrap: wrap; margin-bottom: 10px; }
.row-inputs .u-label { display: flex; flex-direction: column; font-size: 12px; color: var(--text-2); gap: 4px; }
/* `.date-inp`：日期控件是 DateInput 产出的**原生 .u-input**，uni 会把上面的 `.u-input` 改写成
   `uni-input`、匹配不到它，故这里额外挂上它的类名（其余输入框照旧走 uni-input）。
   `.u-select` 是 Picker 组件（自带边框/内边距），这里**只给宽度**，再画边框会变双边框。 */
.row-inputs .u-input, .row-inputs .date-inp {
  border: 1px solid var(--border); border-radius: 7px; padding: 5px 8px;
  font-size: 13px; background: var(--card); color: var(--text); min-width: 90px;
}
.row-inputs .u-select { min-width: 90px; }
.row-inputs .u-input[type='number'] { min-width: 70px; }

/* 开关 */
/* 开关：纯 view + 点击（见模板注释）。选中态靠 .switch.on 这个类名 ——
   ⚠️ 别写回 `input:checked + .slider`：uni 的 <input> 不认 checkbox（type 被抹成 text），
   伪类永远不匹配，表现为「滑块永远是灰的、点了也没反应」（2026-09-23 修）。 */
.switch { position: relative; display: inline-block; width: 44px; height: 24px; cursor: pointer; }
.slider { position: absolute; top: 0; right: 0; bottom: 0; left: 0; background: var(--track); border-radius: 999px; transition: 0.2s; cursor: pointer; }
.slider::before { content: ''; position: absolute; width: 18px; height: 18px; left: 3px; top: 3px; background: var(--card); border-radius: 50%; transition: 0.2s; }
.switch.on .slider { background: var(--primary); }
.switch.on .slider::before { transform: translateX(20px); }

</style>
