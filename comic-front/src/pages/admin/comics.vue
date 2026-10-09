<script setup lang="ts">
// 作品管理（/#/admin/comics）—— 管理台的**第 2 个选项卡**（管理员及以上，`requireRole(false)`）
//
// ⚠️ 它是管理台的一栏，**不进抽屉菜单**（2026-10-09 用户要求「作品管理放在管理台同一页面、
// 不同选项卡上」）：入口仍是抽屉里的「采集管理」，进来后用顶部选项卡切到这一栏。
// 选项卡栏见 `components/AdminTabs.vue`（导航式 —— 各页仍是独立路由，可直达可分享）。
//
// 三件事：
//   ① **上下架**：下架后前台立刻不可见（列表 / 搜索 / 收藏 / 历史 / 详情页 404），
//      但**不删数据**、采集照旧更新，重新上架即恢复；
//   ② **评论开关**：顶部是**全站总开关**，每行是该作品的**单作品开关**；
//      有效值 = 两者都开（AND）—— 所以总闸关掉时，下面打开也没用（界面上有说明）；
//      关掉后详情页**整块评论区都不渲染**。
//   ③ **补全章节**：按 `(源, 源作品 ID)` 幂等复用「按需导入」（`POST /api/admin/import`）——
//      补齐库内缺失的**所有**章节（含中间空洞），只抓一次详情、不下载正文图。
//      ⚠️ 这是「作品掉出源站『最近更新』列表后章节补不齐」的解法：采集只能碰到列表里的
//      作品（增量/全量都翻列表，受 `MAX_PAGES_PER_SYNC` 页数约束），而按作品定位的导入
//      **不依赖列表**（2026-10-09 用户问「不在定时任务内、章节不完整能不能补」，故加入口）。
//
// ⚠️ **本页不做评论浏览**（2026-10-09 用户明确「这么多评论不可能一个个去看的」）——
// 原先每行的「查看评论」展开面板已删除。真要清理某条评论，去**漫画详情页的评论区**删
// （管理员在那里逐条看得到「删除」按钮，是"看到问题顺手删"的场景，不是"逐部巡检"）。
// 后端 `GET /api/admin/comics/{id}/comments` 仍保留（下架作品的评论只有它能看），只是本页不再用。
//
// ⚠️ 本页是**搜索式**的：**不默认列出全部作品** —— 输入关键词（标题 / 作者 / 分类 / 标签）
// 点「搜索」才拉数据（2026-10-09 用户要求「不需要列出所有的漫画，只要根据搜索框输入关键字
// 查找就可以」）。搜索范围含**已下架**的作品（与前台相反，前台一律只给已上架的）。
// 卡片式布局（不是表格）：与「窄屏不许横向滚动条」的约定一致，不做响应式分支。
import { computed, ref } from 'vue'
import { onLoad } from '@dcloudio/uni-app'
import {
  getAdminComics,
  getCommentSetting,
  importAndWait,
  setCommentSetting,
  setComicComment,
  setComicListed,
} from '../../api'
import type { AdminComic } from '../../types'
import { setRoute } from '../../utils/router'
import { requireRole } from '../../utils/guard'
import AdminTabs from '../../components/AdminTabs.vue'
import Layout from '../../components/Layout.vue'

const ready = ref(false)
const items = ref<AdminComic[]>([])
const total = ref(0)
const page = ref(1)
const pageSize = 20
const keyword = ref('')
const loading = ref(false)
const error = ref('')
const busyId = ref<number | null>(null)   // 正在切开关的那一行（防重复点击）
/**
 * 「补全章节」的行内状态：comic_id → 文案（空 = 不显示）。
 *
 * 补章跟着那一行走（不弹全局提示）：按钮点在下方的卡片上、提示就该显示在同处，
 * 滚到页面中段时顶部提示是看不见的。`load()` 重建 items 不影响它（按 id 键）。
 */
const fillingId = ref<number | null>(null)          // 正在补章的那一行（防重复点击）
const fillState = ref<Record<number, string>>({})   // 补章结果文案（含「补章中…」）
/**
 * 是否已执行过一次搜索。
 * ⚠️ **不默认列全部**（2026-10-09 用户要求）：「作品管理不需要列出所有的漫画，
 * 只要根据搜索框输入关键字查找就可以」—— 库大了以后全量列表既慢又没用，
 * 进来就是一屏搜索结果。所以初始态是空的，必须输入关键词才会拉数据。
 */
const searched = ref(false)

// 全站评论总开关
const globalComment = ref(true)
const globalBusy = ref(false)

const totalPages = computed(() => Math.max(1, Math.ceil(total.value / pageSize.value)))

function fmtDay(iso: string): string {
  const d = new Date(iso)
  return `${d.getMonth() + 1}月${d.getDate()}日`
}

async function load() {
  loading.value = true
  error.value = ''
  try {
    const r = await getAdminComics({
      keyword: keyword.value.trim() || undefined,
      page: page.value,
      pageSize,
    })
    items.value = r.items
    total.value = r.total
  } catch (e) {
    error.value = (e as Error).message || '加载作品失败'
  } finally {
    loading.value = false
  }
}

async function loadGlobalSetting() {
  try {
    globalComment.value = (await getCommentSetting()).enabled
  } catch {
    /* 读不到就按默认「开」显示，用户点一下会拿到真实错误 */
  }
}

/** 搜索（**必须有关键词** —— 空关键词不做全量列表，见 `searched` 的说明） */
function search() {
  if (!keyword.value.trim()) {
    error.value = '请输入关键词（标题 / 作者 / 分类 / 标签）后再搜索'
    return
  }
  page.value = 1
  searched.value = true
  fillState.value = {}          // 新一轮结果不带上一轮的补章提示
  void load()
}

function go(delta: number) {
  const next = page.value + delta
  if (next < 1 || next > totalPages.value) return
  page.value = next
  fillState.value = {}
  void load()
}

/** 上下架（后端还会再拦一次；失败把中文原因显示在面板顶部） */
async function toggleListed(c: AdminComic) {
  if (busyId.value !== null) return
  busyId.value = c.id
  error.value = ''
  try {
    const r = await setComicListed(c.id, !c.listed)
    c.listed = r.listed
  } catch (e) {
    error.value = (e as Error).message || '操作失败'
  } finally {
    busyId.value = null
  }
}

/** 单作品评论开关 */
async function toggleComicComment(c: AdminComic) {
  if (busyId.value !== null) return
  busyId.value = c.id
  error.value = ''
  try {
    const r = await setComicComment(c.id, !c.commentEnabled)
    c.commentEnabled = r.commentEnabled
  } catch (e) {
    error.value = (e as Error).message || '操作失败'
  } finally {
    busyId.value = null
  }
}

/** 全站评论总开关 */
async function toggleGlobalComment() {
  if (globalBusy.value) return
  globalBusy.value = true
  error.value = ''
  try {
    globalComment.value = (await setCommentSetting(!globalComment.value)).enabled
  } catch (e) {
    error.value = (e as Error).message || '操作失败'
  } finally {
    globalBusy.value = false
  }
}

/**
 * 「补全章节」：按 `(源, 源作品 ID)` 幂等复用「按需导入」—— 补齐库内缺失的**所有**章节
 * （含中间空洞）；只抓一次详情、**不下载正文图**（1~3 秒完成）。
 *
 * 为什么不走「触发采集」：采集只翻源站「最近更新」列表（增量 / 全量都受
 * `MAX_PAGES_PER_SYNC` 页数约束），掉出列表的作品它永远碰不到；这里按作品精确定位、
 * **不依赖列表**。已下架作品也能补（补章与前台可见性无关）；源站锁定 / 收费的作品
 * 会被合规闸门挡下（原因显示在页面顶部）。
 */
async function fillChapters(c: AdminComic) {
  if (busyId.value !== null || fillingId.value !== null) return
  if (!c.sourceComicId) {
    error.value = '该作品缺少源站作品 ID，无法定位补章'
    return
  }
  fillingId.value = c.id
  error.value = ''
  fillState.value[c.id] = '补章中…'
  try {
    const r = await importAndWait({ source: c.source, sourceComicId: c.sourceComicId })
    fillState.value[c.id] = r.newChapters
      ? `已补齐 ${r.newChapters} 话（库内共 ${r.chapters} 话）`
      : `无缺失章节（库内共 ${r.chapters} 话）`
    // 补完章节数 / 最近更新时间可能变了 —— 重拉当前页（保持搜索词与页码；提示按 id 保留）
    void load()
  } catch (e) {
    fillState.value[c.id] = ''
    error.value = (e as Error).message || '补章失败'
  } finally {
    fillingId.value = null
  }
}

onLoad(async (options) => {
  // uni 页面生命周期：登记该页对应的 web 路径（替代 vue-router 的路由状态）
  setRoute('/admin/comics', options ?? {})
  // 门卫：管理台一级门（超管与普通管理员都能进）—— 与「采集管理」同一档
  if (!(await requireRole(false, '/admin/comics'))) return
  ready.value = true
  // ⚠️ 这里**不调 load()**：不列全部作品，等用户输入关键词再搜（见 `searched`）。
  // 全站总开关与搜索无关，照常先读。
  void loadGlobalSetting()
})
</script>

<template>
  <Layout>
    <view v-if="ready">
      <!-- 管理台同一栏的选项卡（采集管理 / 作品管理 / 定时任务 / 运行日志）——
           本页是其中的「作品管理」，故 current="comics"（见 components/AdminTabs.vue） -->
      <view class="title-row">
        <AdminTabs current="comics" />
      </view>
      <view class="lead u-p">
        <text class="u-b">下架</text>后该作品在前台立刻消失（列表 / 搜索 / 收藏 / 历史都查不到，
        详情页 404），但<text class="u-b">数据与图片都保留</text>，采集也照旧更新 —— 重新上架即恢复。
        评论开关是<text class="u-b">两级</text>：下面的全站总开关 + 每部作品的单独开关，
        <text class="u-b">两边都开</text>才能评论；关掉后详情页<text class="u-b">整块评论区都不显示</text>。
      </view>

      <!-- 全站评论总开关 -->
      <view class="global-card">
        <view class="g-left">
          <view class="g-title u-h3">全站评论总开关</view>
          <view class="g-sub u-p">
            关掉后所有作品的评论区一起停（各作品的单独开关保持原样、不被覆盖）。
          </view>
        </view>
        <view
          class="switch"
          :class="{ on: globalComment }"
          :title="globalComment ? '点击关闭全站评论' : '点击开启全站评论'"
          @click="toggleGlobalComment"
        >
          <text class="slider u-span"></text>
        </view>
      </view>

      <view class="toolbar">
        <form class="search" @submit="search">
          <input
            class="u-input"
            v-model="keyword"
            type="text"
            placeholder="搜索标题 / 作者 / 分类 / 标签"
            @confirm="search"
          />
          <button class="btn u-button" form-type="submit">搜索</button>
        </form>
        <text v-if="searched" class="total u-span">命中 {{ total }} 部（含已下架）</text>
      </view>

      <view v-if="error" class="notice u-p">{{ error }}</view>

      <!-- ⚠️ 不默认列全部：没搜过就给一句话，而不是拉一屏数据（见 `searched` 的说明） -->
      <view v-if="!searched" class="empty">输入关键词后点「搜索」查找作品</view>
      <view v-else-if="loading" class="empty">加载中…</view>
      <view v-else-if="!items.length" class="empty">没有匹配的作品</view>

      <view v-else class="list">
        <view v-for="c in items" :key="c.id" class="item" :class="{ offline: !c.listed }">
          <view class="i-head">
            <text class="i-title u-h3" :title="c.title">{{ c.title }}</text>
            <text class="i-state u-span" :class="c.listed ? 'on' : 'off'">
              {{ c.listed ? '已上架' : '已下架' }}
            </text>
          </view>
          <view class="i-meta u-p">
            #{{ c.id }} · {{ c.source }} · {{ c.chapterCount }} 话 · 更新 {{ fmtDay(c.updatedAt) }}
          </view>

          <view class="i-actions">
            <view class="act">
              <text class="act-label u-span">上下架</text>
              <view
                class="switch sm"
                :class="{ on: c.listed }"
                :title="c.listed ? '点击下架' : '点击上架'"
                @click="toggleListed(c)"
              >
                <text class="slider u-span"></text>
              </view>
            </view>
            <view class="act">
              <text class="act-label u-span">评论</text>
              <view
                class="switch sm"
                :class="{ on: c.commentEnabled }"
                :title="c.commentEnabled ? '点击关闭该作品评论区' : '点击开启该作品评论区'"
                @click="toggleComicComment(c)"
              >
                <text class="slider u-span"></text>
              </view>
            </view>
            <!-- 补全章节：按源站目录补齐缺失章节（复用「按需导入」，不依赖采集列表、不下载图片） -->
            <view class="act">
              <text class="act-label u-span">章节</text>
              <button
                class="btn ghost u-button act-btn"
                :disabled="busyId !== null || fillingId !== null"
                title="按源站目录补齐缺失的章节（不下载图片，1~3 秒）"
                @click="fillChapters(c)"
              >{{ fillingId === c.id ? '补章中…' : '补全章节' }}</button>
              <text v-if="fillState[c.id]" class="fill-msg u-span">{{ fillState[c.id] }}</text>
            </view>
          </view>
        </view>
      </view>

      <view v-if="searched && totalPages > 1" class="pager">
        <button class="btn ghost u-button" :disabled="page <= 1" @click="go(-1)">上一页</button>
        <text class="page-info u-span">{{ page }} / {{ totalPages }}</text>
        <button class="btn ghost u-button" :disabled="page >= totalPages" @click="go(1)">下一页</button>
      </view>
    </view>
  </Layout>
</template>

<style scoped>
.title-row { display: flex; align-items: center; gap: 12px; }

.lead { color: var(--text-2); font-size: 14px; margin: 12px 0 16px; line-height: 1.7; }
.lead .u-b { color: var(--primary-dark); }

.global-card {
  display: flex; align-items: center; gap: 14px;
  background: var(--card); border: 1px solid var(--border); border-radius: 14px;
  padding: 14px 16px; box-shadow: var(--shadow); margin-bottom: 14px;
}
.global-card .g-left { flex: 1; min-width: 0; }
.global-card .g-title { margin: 0; font-size: 15px; }
.global-card .g-sub { margin: 4px 0 0; font-size: 12px; color: var(--text-2); line-height: 1.6; }

.toolbar { display: flex; align-items: center; gap: 12px; flex-wrap: wrap; margin: 0 0 14px; }
.search { display: flex; gap: 8px; flex: 1 1 260px; min-width: 0; }
.search .u-input {
  flex: 1; min-width: 0; padding: 7px 12px; border: 1px solid var(--border);
  border-radius: 8px; background: var(--card); color: var(--text); font-size: 13px;
}
.total { color: var(--text-2); font-size: 13px; }

.notice {
  font-size: 13px; color: var(--primary-dark); background: var(--primary-soft);
  border-radius: 8px; padding: 8px 12px; margin-bottom: 12px;
}

.list { display: flex; flex-direction: column; gap: 12px; }
.item { background: var(--card); border: 1px solid var(--border); border-radius: 12px; padding: 12px 14px; }
/* 已下架：整条降透明度 + 虚线框，一眼能扫出哪些不在前台 */
.item.offline { opacity: 0.72; border-style: dashed; }
.i-head { display: flex; align-items: center; gap: 10px; }
.i-title { margin: 0; font-size: 15px; flex: 1; min-width: 0; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.i-state { flex: none; font-size: 11px; padding: 2px 8px; border-radius: 999px; font-weight: 700; }
.i-state.on { background: var(--primary-soft); color: var(--primary-dark); }
.i-state.off { background: var(--mute); color: var(--text-2); }
.i-meta { margin: 6px 0 0; font-size: 12px; color: var(--text-2); }

.i-actions { display: flex; align-items: center; gap: 18px; margin-top: 10px; flex-wrap: wrap; }
.act { display: flex; align-items: center; gap: 8px; }
.act-label { font-size: 13px; color: var(--text-2); }

/* 「补全章节」按钮：比全局 .btn 小一号（行内控件，与 21px 高的开关同排） */
.act-btn { font-size: 12px; padding: 4px 12px; }
/* 补章结果跟着那一行走（「已补齐 N 话」/「无缺失章节」）—— 滚到页面中段时顶部提示看不见 */
.fill-msg { font-size: 12px; color: var(--primary-dark); }

/* 开关：纯 view + 点击 —— **不能用原生 checkbox**（uni 的 <input> 有 type 白名单，
   checkbox 会被抹成 text），选中态靠 `.switch.on` 类名。与 pages/admin/index.vue 同一套。 */
.switch { position: relative; display: inline-block; width: 44px; height: 24px; cursor: pointer; flex: none; }
.switch.sm { width: 38px; height: 21px; }
.slider { position: absolute; top: 0; right: 0; bottom: 0; left: 0; background: var(--track); border-radius: 999px; transition: 0.2s; }
.slider::before { content: ''; position: absolute; width: 18px; height: 18px; left: 3px; top: 3px; background: var(--card); border-radius: 50%; transition: 0.2s; }
.switch.on .slider { background: var(--primary); }
.switch.on .slider::before { transform: translateX(20px); }
.switch.sm .slider::before { width: 15px; height: 15px; }
.switch.sm.on .slider::before { transform: translateX(17px); }

.pager { display: flex; align-items: center; justify-content: center; gap: 16px; margin-top: 22px; }
.page-info { color: var(--text-2); font-size: 14px; }
</style>
