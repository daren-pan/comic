<script setup lang="ts">
import { onMounted, ref } from 'vue'
import {
  getAdminSources,
  toggleAdminSource,
  startAdminSync,
  startAdminInspect,
  startAdminHealCovers,
} from '../api'
import { useMessageStore } from '../stores/message'
import type { PickerOption, SourceInfo } from '../types'
import { showAlert } from '../utils/ui'
import { formatDateTime, formatInterval } from '../utils/format'
import Layout from '../components/Layout.vue'
import AdminTabs from '../components/AdminTabs.vue'
import DateInput from '../components/DateInput.vue'
import Picker from '../components/Picker.vue'

// 每个源的采集操作表单状态（独立参数）
interface SourceVM {
  info: SourceInfo
  syncMode: 'incremental' | 'full'
  syncSince: string   // 起始日期（yyyy-MM-dd 或空）
  syncLimit: string   // 数量（空=不限）
  running: boolean    // 是否正在触发（防重复点击）
}

// 采集模式下拉：统一走 Picker（见 components/Picker.vue）
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
// 挂载后置 true 渲染页面主体（门卫由路由层 beforeEnter 承担）
const ready = ref(false)

// 失效巡检是**全库**动作（扫描整张 page 表），故不放进各源卡片，页面顶部独占一个面板；
// 封面自愈面板则按**指定作品**（名称/ID）强制刷新封面。
const inspectSince = ref('')
const inspectUntil = ref('')
const inspecting = ref(false)
const healing = ref(false)       // 按作品封面自愈是否正在触发
const healKeyword = ref('')      // 漫画名称或 ID（可多个，逗号/空格/换行分隔）—— 不允许留空

// 任务结果一律写入全局消息中心（顶栏 🔔 可见，离开本页也会继续跟踪到结束）
const msgStore = useMessageStore()

// 时间 / 间隔格式化已收进 `utils/format.ts`（2026-10-13）：
// 这里的 `fmtTime`/`fmtInterval` 与 me、schedule 两页的同名实现原本各写一份。

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
    void showAlert((e as Error).message || '切换失败')
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
    await startAdminSync(body)
    // 任务已落库：立刻刷新消息中心（先出现一条"进行中"条目，跑完由服务端补一条结果消息）
    msgStore.refresh()
  } catch (e) {
    void showAlert((e as Error).message || '触发采集失败')
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
    await startAdminInspect(body)
    msgStore.refresh()
  } catch (e) {
    void showAlert((e as Error).message || '触发失效巡检失败')
  } finally {
    inspecting.value = false
  }
}

// 按作品封面自愈：填漫画名称或 ID（可多个）→ **强制**回源重抓封面并覆盖（修「文件在但内容错」的封面）
async function runHealCovers() {
  if (healing.value) return
  const keyword = healKeyword.value.trim()
  if (!keyword) {
    void showAlert('请填写漫画名称或 ID（可多个，用逗号/空格/换行分隔）')
    return
  }
  healing.value = true
  try {
    await startAdminHealCovers({ keyword })
    msgStore.refresh()
  } catch (e) {
    void showAlert((e as Error).message || '触发封面自愈失败')
  } finally {
    healing.value = false
  }
}

onMounted(async () => {
  ready.value = true
  void load()
})

</script>

<template>
  <Layout>
    <div v-if="ready">
      <!-- 管理台同一栏的三个选项卡（采集管理 / 定时任务 / 运行日志）—— 点选项切换，
           不再各放一个跳转按钮（那三个入口就是这几个选项，见 components/AdminTabs.vue） -->
      <div class="title-row">
        <AdminTabs current="admin" />
      </div>
      <div class="lead u-p">
        手动触发各数据源的采集；关闭的源将拒绝触发采集。
        顶部的<span class="u-b">失效巡检</span>是<span class="u-b">全库维护的唯一入口</span>（转存未转存页 + 全表校验恢复 + 封面自愈）；
        <span class="u-b">封面自愈</span>按<span class="u-b">指定作品</span>（名称/ID）强制刷新。
        任务进度与结果见右上角 <span class="u-b">🔔 消息</span>（含历史记录，执行完毕会有提示）。
      </div>

      <div v-if="error" class="empty" style="color:#e23">{{ error }}</div>
      <div v-else-if="!loaded" class="empty">加载数据源中…</div>

      <template v-else>
        <!-- 全库维护区：失效巡检（全库）+ 封面自愈（按指定作品），不放各源卡片内 -->
        <div class="maint-row">
          <!-- 失效巡检：全库动作（扫描整张 page 表） -->
          <div class="maintenance">
            <div class="maint-head">
              <span class="maint-title u-span">失效巡检</span>
              <span class="maint-tag u-span">全库</span>
            </div>
            <div class="maint-desc u-p">
              <span class="u-b">全库维护的唯一入口</span>：把所选时间范围内的未转存页<span class="u-b">全部转存</span>、
              <span class="u-b">全表校验</span>已转存对象是否还在（缺失自动恢复），并做<span class="u-b">全库封面自愈</span>
              （起止留空 = 全库）。
            </div>
            <div class="row-inputs">
              <div class="u-label">起始
                <DateInput
                  :model-value="inspectSince"
                  @update:model-value="inspectSince = $event"
                />
              </div>
              <div class="u-label">截止（含当天）
                <DateInput
                  :model-value="inspectUntil"
                  @update:model-value="inspectUntil = $event"
                />
              </div>
            </div>
            <button class="btn ghost u-button" :disabled="inspecting" @click="runInspect">
              {{ inspecting ? '运行中…' : '触发巡检' }}
            </button>
          </div>

          <!-- 封面自愈：按指定作品（名称/ID）强制刷新封面，只修封面、不转存正文页 -->
          <div class="maintenance">
            <div class="maint-head">
              <span class="maint-title u-span">封面自愈</span>
              <span class="maint-tag cover u-span">指定作品</span>
            </div>
            <div class="maint-desc u-p">
              填漫画名称或 ID（可多个）→ <span class="u-b">强制</span>回源重抓封面并覆盖，专治<span class="u-b">「封面文件在、但内容是错的」</span>
              （普通自愈只看文件在不在，永远修不到错图）。只修封面、<span class="u-b">不转存正文页</span>。
            </div>
            <div class="heal-field u-label">
              漫画名称或 ID（可多个，逗号 / 空格 / 换行分隔）
              <textarea class="u-textarea" v-model="healKeyword" rows="2" placeholder="如：电锯人, 17, 海贼王"></textarea>
            </div>
            <button class="btn ghost u-button" :disabled="healing" @click="runHealCovers">
              {{ healing ? '运行中…' : '触发封面自愈' }}
            </button>
          </div>
        </div>

        <!-- 数据源卡片 -->
        <div class="grid">
          <div v-for="vm in sources" :key="vm.info.name" class="card">
            <div class="card-head">
              <div class="head-left">
                <span class="src-name u-span">{{ vm.info.name }}</span>
                <span class="chip pri u-span" :class="vm.info.priority">{{ vm.info.priority === 'primary' ? '主源' : '备源' }}</span>
              </div>
              <!-- 开关：**不能用原生 checkbox** —— uni 的 <input> 有 type 白名单（不含 checkbox，
                   会被抹成 text），且 <label> 已被映射成 view、失去「点容器激活内部控件」的能力。
                   所以这里不依赖任何原生控件：纯 view + 显式点击，选中态走类名（见 <style>）。 -->
              <div
                class="switch"
                :class="{ on: vm.info.enabled }"
                :title="vm.info.enabled ? '点击关闭采集' : '点击开启采集'"
                @click="toggleSource(vm)"
              >
                <span class="slider u-span"></span>
              </div>
            </div>

            <div class="card-meta">
              <span class="u-span">库内 <span class="u-b">{{ vm.info.comicCount }}</span> 部</span>
              <span class="u-span">间隔 <span class="u-b">{{ formatInterval(vm.info.interval) }}</span></span>
              <span class="u-span">上次同步 <span class="u-b">{{ formatDateTime(vm.info.lastSync) }}</span></span>
            </div>

            <!-- 采集区 -->
            <div class="panel">
              <div class="panel-title">采集</div>
              <div class="row-inputs">
                <div class="u-label">模式
                  <Picker
                    class="u-select"
                    :model-value="vm.syncMode"
                    :options="syncModeOptions"
                    @update:model-value="onSyncMode(vm, $event)"
                  />
                </div>
                <div class="u-label">起始日期
                  <DateInput
                    :model-value="vm.syncSince"
                    @update:model-value="vm.syncSince = $event"
                  />
                </div>
                <div class="u-label">数量
                  <input class="u-input" v-model="vm.syncLimit" type="number" min="1" placeholder="不限" />
                </div>
              </div>
              <!-- 翻页安全阀（`MAX_PAGES_PER_SYNC = 5`）对增量与全量一视同仁，页面得说清，
                   否则「全量」会被误读成"扫全库"（2026-10-07 用户反馈）。
                   ⚠️ 文案要**短到窄屏一行放得下**（2026-10-09 用户要求「精简成一行」）——
                   加字前先量 393 视口下的实际宽度。 -->
              <span class="hint u-span">
                每轮最多 <span class="u-b">5 页 ≈ 100 部</span>，全量 / 增量同限，多了分批
              </span>
              <!-- ⚠️ 按钮包一层块级 view：`.btn` 是 `inline-flex`，裸着跟在 `.hint`（行内 text）
                   后面会排进**同一行流** —— 窄屏实测「触发采集」挤在文字右端（2026-10-09 用户报）。
                   包一层后单独占一行、左对齐（`.run-row` 只做这件事）。 -->
              <div class="run-row">
                <button class="btn u-button" :disabled="vm.running || !vm.info.enabled" @click="runSync(vm)">
                  {{ vm.running ? '运行中…' : '触发采集' }}
                </button>
              </div>
            </div>
          </div>
        </div>
      </template>

      <!-- ⚠️ 这里原来有一块「最近任务」（读 `admin_task` 的 20 条 + 只看我的）。
           2026-10-06 **并入消息中心**：任务收尾会往 `message` 表发一条（收件范围 = 管理员及以上），
           定时轮次在跑的时候还会以"进行中"条目临时出现在列表里 —— 所以历史与实时都在
           顶栏铃铛 → `/#/pages/messages/index` 那一处看，不再各画一遍。
           触发任务后本页只需 `msgStore.refresh()`（见上面三处 runXxx）。 -->

    </div>
  </Layout>
</template>

<style scoped>
/* 顶部那一栏：管理台三个选项卡（采集管理 / 定时任务 / 运行日志，见 components/AdminTabs.vue）。
   原来这里的「⏰ 定时任务 / 📄 运行日志」两个跳转按钮已改成同一栏里的选项，
   故不再需要"按钮靠右 / 入口组靠右"那几条规则（外层间距仍由本行统一控制）。 */
.title-row {
  display: flex;
  align-items: center;
  gap: 12px;
  flex-wrap: wrap;
  margin: 28px 0 6px;
}

.lead { color: var(--text-2); font-size: 14px; margin: 0 0 16px; }
.lead .u-b { color: var(--primary-dark); }
/* 表单下方的提示行（与定时任务页同构：小字、弱色；`.u-b` 只作加重） */
.hint { color: var(--text-2); font-size: 12px; }
.hint .u-b { color: var(--text); }

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

/* 「触发采集」按钮行：单独一行、左对齐 —— `.btn` 是 inline-flex，不包一层会跟上面的
   `.hint` 文字排进同一行流（2026-10-09 用户报「挤在文字右边」）。 */
.run-row { display: flex; margin-top: 8px; }

/* 开关 */
/* 开关：纯 view + 点击（见模板注释）。选中态靠 .switch.on 这个类名 ——
   ⚠️ 别写回 `input:checked + .slider`：uni 的 <input> 不认 checkbox（type 被抹成 text），
   伪类永远不匹配，表现为「滑块永远是灰的、点了也没反应」（2026-09-23 修）。 */
.switch { position: relative; display: inline-block; width: 44px; height: 24px; cursor: pointer; }
.slider { position: absolute; top: 0; right: 0; bottom: 0; left: 0; background: var(--track); border-radius: 999px; transition: 0.2s; cursor: pointer; }
.slider::before { content: ''; position: absolute; width: 18px; height: 18px; left: 3px; top: 3px; background: var(--card); border-radius: 50%; transition: 0.2s; }
.switch.on .slider { background: var(--primary); }
.switch.on .slider::before { transform: translateX(20px); }

/* ---- 窄屏（≤860px）：卡片区单列铺开 ----
   上面两块卡片区都用了 `minmax(360px, 1fr)`，360px 是**硬下限**：窄屏内容区不足 360px 时
   列宽仍按 360px 撑开 —— 实测 393 视口溢出 7px（左右边距 16/9 不对称），360 视口直接出
   **整页横向滚动条**（scrollWidth 376 > clientWidth 352）。窄屏降到 1fr 即可消除。
   本页是卡片、没有「列太多的表格」，故不做伸缩展开。断点与 `Layout.vue` 一致。 */
@media (max-width: 860px) {
  .grid,
  .maint-row { grid-template-columns: 1fr; }
}

</style>
