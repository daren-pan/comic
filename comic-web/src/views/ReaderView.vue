<script setup lang="ts">
// 阅读器。
//
// ⚠️ 实现说明：
//   - `PointerEvent`            → 增加 `touchstart/touchend` 双轨（触屏设备）+ 保留 pointer（桌面鼠标拖拽）
//   - `requestAnimationFrame`   → 改为 `setTimeout` 节流
//   - `element.scrollTo`        → 竖排连播用 `scrollIntoView` 定位页块（原生滚动容器）
//   - `e.clientX`               → 统一由 `eventX()` 取（优先 `clientX`，兜底 `detail.x`）
//   - `e.currentTarget`         → 进度条点击改为按需量轨道位置（只在点击时量，不是热路径）
// **业务判定规则一字未改**：滑动阈值 60px / 800ms、左右热区各 25%、当前页取"视口中心最近的那页"。
import { computed, nextTick, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { getChapters, getChapter, getChapterPages, getHistory, upsertHistory } from '../api'
import { useRoute, useRouter } from 'vue-router'
import { parentOf } from '../utils/nav'
import { storage } from '../utils/storage'
import Layout from '../components/Layout.vue'
import type { Chapter, PageInfo } from '../types'

const route = useRoute()
const router = useRouter()
// 路由参数来自 vue-router（`/reader/:comicId/:chapterId`）
let comicId = 0
const chapterId = ref(0)

const chapters = ref<Chapter[]>([])
const chapter = ref<Chapter>()
const pages = ref<PageInfo[]>([])
const pageNo = ref(1)
const loading = ref(true)
const imgLoading = ref(true)
const showBar = ref(true)
const showMenu = ref(false)
const showSettings = ref(false)
const theme = ref<'dark' | 'light'>('dark')
// 阅读模式：horizontal = 左右滑动单张翻页；vertical = 竖排连播下拉
const mode = ref<'horizontal' | 'vertical'>('horizontal')

const chapterIdx = computed(() => chapters.value.findIndex((c) => c.id === chapterId.value))
const hasPrev = computed(() => chapterIdx.value > 0)
const hasNext = computed(() => chapterIdx.value >= 0 && chapterIdx.value < chapters.value.length - 1)
const total = computed(() => pages.value.length)
// 进度条百分比：跟随 `shownPage`（拖动中即预览值），定义见下方「底部进度条」一节
const progress = computed(() => (total.value ? Math.round((shownPage.value / total.value) * 100) : 0))
const isVertical = computed(() => mode.value === 'vertical')

// 横向模式懒加载：仅当前页与前后各一页真实渲染
function isNear(p: number) {
  return Math.abs(p - pageNo.value) <= 1
}

// ---------------- 坐标 / 测量 ----------------
/** 取事件里的横坐标（优先 `clientX`，兜底 `detail.x`） */
function eventX(e: unknown): number {
  const ev = e as { clientX?: number; detail?: { x?: number } }
  return ev.clientX ?? ev.detail?.x ?? 0
}

/** 触摸点坐标（touchstart 读 touches、touchend 读 changedTouches） */
function touchPoint(e: unknown): { x: number; y: number } | null {
  const ev = e as {
    touches?: Array<{ clientX?: number; pageX?: number; clientY?: number; pageY?: number }>
    changedTouches?: Array<{ clientX?: number; pageX?: number; clientY?: number; pageY?: number }>
  }
  const t = ev.touches?.[0] ?? ev.changedTouches?.[0]
  if (!t) return null
  return { x: t.clientX ?? t.pageX ?? 0, y: t.clientY ?? t.pageY ?? 0 }
}

/** 量一个节点的位置（原生，同步） */
function measureOne(
  selector: string,
  cb: (rect: { left: number; top: number; width: number; height: number } | null) => void,
) {
  const el = document.querySelector(selector)
  if (!el) {
    cb(null)
    return
  }
  const r = el.getBoundingClientRect()
  cb({ left: r.left, top: r.top, width: r.width, height: r.height })
}

/** 量一批节点的位置（原生，同步）；带上 `dataset`（调用方用 `data-page` 取页码） */
function measureAll(
  selector: string,
  cb: (
    rects: Array<{ left: number; top: number; width: number; height: number; dataset: DOMStringMap }>,
  ) => void,
) {
  const els = Array.from(document.querySelectorAll(selector))
  cb(
    els.map((el) => {
      const r = el.getBoundingClientRect()
      return { left: r.left, top: r.top, width: r.width, height: r.height, dataset: el.dataset }
    }),
  )
}

// ---------------- 设置持久化 ----------------
function loadSettings() {
  try {
    const s = JSON.parse(storage.get('comic_reader_settings') || '{}')
    if (s.theme === 'light' || s.theme === 'dark') theme.value = s.theme
    if (s.mode === 'horizontal' || s.mode === 'vertical') mode.value = s.mode
  } catch {
    /* ignore */
  }
}
function saveSettings() {
  storage.set('comic_reader_settings', JSON.stringify({ theme: theme.value, mode: mode.value }))
}
function setTheme(t: 'dark' | 'light') {
  theme.value = t
  saveSettings()
}
function setMode(m: 'horizontal' | 'vertical') {
  if (m === mode.value) return
  mode.value = m
  saveSettings()
  showSettings.value = false
  nextTick(() => {
    // 切到竖排：定位回当前页；切到横向：单张居中，本来就没有滚动位置
    if (m === 'vertical') scrollToPage(pageNo.value)
  })
}

// ---------------- 章节加载 ----------------
async function loadChapter(id: number) {
  loading.value = true
  chapter.value = await getChapter(comicId, id)
  pages.value = await getChapterPages(comicId, id)
  pageNo.value = 1
  imgLoading.value = true
  loading.value = false
  await nextTick()
  if (isVertical.value) scrollToPage(1)
}

function goChapter(id: number) {
  // 同页跳转：compat 层会把地址栏换成 #/reader/<comicId>/<id>（H5）
  chapterId.value = id
  router.replace(`/reader/${comicId}/${id}`)
  void loadChapter(id)
  showMenu.value = false
}

function prevChapter() {
  if (hasPrev.value) goChapter(chapters.value[chapterIdx.value - 1].id)
}
function nextChapter() {
  if (hasNext.value) goChapter(chapters.value[chapterIdx.value + 1].id)
}

function onImgLoad() {
  imgLoading.value = false
}

// 跳页：两种模式统一入口（垂直=滚动到页顶，横向=回顶+刷新单张）
function goPage(p: number) {
  if (p < 1 || p > total.value) return
  pageNo.value = p
  // ⚠️ 「图片加载中」只对**横排**有意义（单张换图，新 src 必然触发 @load 复位）。
  // 竖排是流式懒加载：目标页的图若已在缓存/已在 DOM，`src` 没变、元素没重建 →
  // `@load` 不会再触发 → imgLoading 卡在 true → 顶部提示块**永久显示**
  // （2026-10-09 实测复现：拖进度条回第 1 页后 3.5s 仍在）。
  if (!isVertical.value) imgLoading.value = true
  if (isVertical.value) scrollToPage(p)
}

// ---------------- 竖排连播：滚动定位 + 当前页推导 ----------------
/** 滚到某页顶部：原生 `scrollIntoView`（页块 id = `pb<页码>`；滚动容器是 .pages-scroll） */
function scrollToPage(p: number) {
  document.getElementById(`pb${p}`)?.scrollIntoView({ block: 'start' })
}

let measureTimer: ReturnType<typeof setTimeout> | undefined
/** 滚动回调：节流后量一次（`setTimeout` 节流） */
function onScroll() {
  if (!isVertical.value) return
  if (measureTimer) return
  measureTimer = setTimeout(() => {
    measureTimer = undefined
    measureCurrentPage()
  }, 120)
}

/** 取「离视口中心最近的那一页」为当前页 —— 与 comic-web 的判定规则完全一致，
 *  只是把 getBoundingClientRect 换成 uni 的选择器查询。 */
function measureCurrentPage() {
  measureOne('#pages-scroll', (vr) => {
    if (!vr || !vr.height) return
    measureAll('.page-block', (blocks) => {
      if (!blocks.length) return
      const viewCenter = vr.top + vr.height * 0.5
      let best = 1
      let bestDist = Infinity
      for (const b of blocks) {
        const dist = Math.abs(b.top + b.height / 2 - viewCenter)
        if (dist < bestDist) {
          bestDist = dist
          best = Number(b.dataset?.page) || best
        }
      }
      if (best !== pageNo.value) pageNo.value = best
    })
  })
}

// ---------------- 横向模式：点击热区 + 滑动翻页 ----------------
const SWIPE_THRESHOLD = 60
const swipe = ref({ x: 0, y: 0, t: 0, active: false })

function beginSwipe(x: number, y: number) {
  if (isVertical.value) return
  swipe.value = { x, y, t: Date.now(), active: true }
}

/** 结束一次滑动：判定与 comic-web 一字不差（<800ms、位移 ≥60px、且横向位移不小于纵向）。
 *  ⚠️ pointer 与 touch 两套绑定都会调它 —— 靠 `active` 守卫天然去重：
 *     第一个到达的把 active 置 false，第二个直接 return。 */
function endSwipe(x: number, y: number) {
  if (isVertical.value || !swipe.value.active) return
  const dx = x - swipe.value.x
  const dy = y - swipe.value.y
  const dt = Date.now() - swipe.value.t
  swipe.value.active = false
  if (dt > 800) return
  const ax = Math.abs(dx)
  const ay = Math.abs(dy)
  if (Math.max(ax, ay) < SWIPE_THRESHOLD) return
  // 横向模式：左右滑动翻页（左滑下一页 / 右滑上一页）
  if (ax >= ay) {
    if (dx < 0) goPage(pageNo.value + 1)
    else goPage(pageNo.value - 1)
  }
}

// H5（含桌面鼠标拖拽）：pointer 事件
function onPointerDown(e: PointerEvent) {
  if (!e.isPrimary) return
  beginSwipe(e.clientX, e.clientY)
}
function onPointerUp(e: PointerEvent) {
  endSwipe(e.clientX, e.clientY)
}
// 触屏：touch 事件（与上面的 pointer 事件双轨：触摸屏走 touch、桌面鼠标走 pointer）
function onTouchStart(e: unknown) {
  const p = touchPoint(e)
  if (p) beginSwipe(p.x, p.y)
}
function onTouchEnd(e: unknown) {
  const p = touchPoint(e)
  if (p) endSwipe(p.x, p.y)
  else swipe.value.active = false
}
function cancelSwipe() {
  swipe.value.active = false
}

// 视口宽度
function viewportWidth(): number {
  return window.innerWidth
}

// 点击处理：
// - 顶栏隐藏时：点击屏幕中心（水平 25%~75%及垂直上方区域）唤醒顶栏
// - 顶栏可见时：点击中心隐藏顶栏；左右 25% 区翻页
// - 竖排模式：点任意位置仅唤醒/隐藏顶栏（不翻页，避免误触）
function onTapZone(e: unknown) {
  if (isVertical.value) {
    toggleBar()
    return
  }
  const x = eventX(e) / viewportWidth()
  // 点击顶栏区域（上方）或中心区 → 唤醒/隐藏顶栏
  if (x > 0.25 && x < 0.75) {
    toggleBar()
    return
  }
  // 左右 25% 区 → 翻页
  if (x < 0.25) goPage(pageNo.value - 1)
  else if (x > 0.75) goPage(pageNo.value + 1)
}

// ---------------- 底部进度条：点击 + **拖动**跳页 ----------------
// 2026-10-07 用户要求「下方滑动条能够手动滑动到对应页数」——原来只有 `@click` 点击跳页。
// 拖动中只更新**预览值**（进度条与页码跟着动），**松手才真正翻页**：
// 竖排模式的 goPage 会滚动定位，若每次 move 都提交会一路狂滚。
const seeking = ref(false)
const seekPage = ref(1)
/** 进度条上显示/驱动的页号：拖动中显示预览值，否则就是真实页号 */
const shownPage = computed(() => (seeking.value ? seekPage.value : pageNo.value))
/** 轨道位置缓存：拖动开始时量一次，之后每次 move 同步换算 */
let trackRect: { left: number; width: number } | null = null
/** 拖动中最后一次事件（异步测量回来后要拿它补算一次） */
let lastSeekEvent: unknown = null
/** 拖动在"测量回来之前"就结束了 → 测量回调里要立刻补提交，否则会提交到旧页号 */
let seekEndedPending = false

/**
 * 取拖动/点击的横坐标。⚠️ **触摸优先**：`touchstart/touchmove` 的坐标在 `touches[0].clientX`，
 * 事件本身没有 `clientX` —— 只用 `eventX()` 的话手机端每次都算出 0、只能跳到第 1 页
 * （2026-10-07 用户反馈「手机端没法拖拽只能点击」就是这个原因）。
 */
function seekX(e: unknown): number {
  const t = touchPoint(e)
  return t ? t.x : eventX(e)
}

function beginSeek(e: unknown) {
  seeking.value = true
  seekEndedPending = false
  lastSeekEvent = e
  // 拖动期间别让两根栏按 2.6s 计时自己滑走（松手后 commitSeek 会重新计时）
  clearTimeout(hideTimer)
  // 桌面鼠标拖动：move/up 可能跑到轨道外面，所以挂到 document 上
  // （触摸不需要 —— touchmove/touchend 会一直投递给 touchstart 的目标元素）
  document.addEventListener('mousemove', onDocMove)
  document.addEventListener('mouseup', onDocUp)
  // 直接同步量：`uni.createSelectorQuery` 是异步的，**快速点击**会在测量回来之前就 mouseup，
  // 于是提交到上一次的页号（实测点 25% 处停在了上一次拖到的 51/73）。
  const el = document.querySelector('#progress-track')
  if (el) {
    const r = el.getBoundingClientRect()
    applyTrackRect({ left: r.left, width: r.width })
  }
}

function applyTrackRect(r: { left: number; width: number }) {
  trackRect = { left: r.left, width: r.width }
  if (lastSeekEvent) updateSeek(lastSeekEvent)
  if (seekEndedPending) commitSeek()
}

function updateSeek(e: unknown) {
  lastSeekEvent = e
  if (!trackRect || !total.value) return
  const x = seekX(e)
  const ratio = Math.min(1, Math.max(0, (x - trackRect.left) / trackRect.width))
  seekPage.value = Math.min(total.value, Math.max(1, Math.round(ratio * total.value)))
}

function onDocMove(e: MouseEvent) {
  if (seeking.value) updateSeek(e)
}

function onDocUp() {
  endSeek()
}

function endSeek() {
  if (!seeking.value) return
  seeking.value = false
  document.removeEventListener('mousemove', onDocMove)
  document.removeEventListener('mouseup', onDocUp)
  if (trackRect) commitSeek()
  else seekEndedPending = true // 测量还没回来：等 applyTrackRect 补提交
}

function commitSeek() {
  seekEndedPending = false
  trackRect = null
  lastSeekEvent = null
  goPage(seekPage.value)
  pokeBar() // 恢复两根栏的自动隐藏计时（beginSeek 里暂停过）
}

function onKey(e: KeyboardEvent) {
  if (e.key === 'Escape') router.replace(parentOf(route.path))   // 层级返回 → 详情页（不依赖浏览历史，见 utils/nav.ts）
  else if (isVertical.value) {
    if (e.key === 'ArrowDown' || e.key === ' ' || e.key === 'PageDown') goPage(pageNo.value + 1)
    else if (e.key === 'ArrowUp' || e.key === 'PageUp') goPage(pageNo.value - 1)
    else if (e.key === 'ArrowLeft') goPage(pageNo.value - 1)
    else if (e.key === 'ArrowRight') goPage(pageNo.value + 1)
  } else {
    if (e.key === 'ArrowLeft') goPage(pageNo.value - 1)
    else if (e.key === 'ArrowRight') goPage(pageNo.value + 1)
  }
}

// 进度记忆：翻页时写入历史
watch(pageNo, () => {
  if (chapter.value) upsertHistory({ comicId, chapterId: chapter.value.id, pageNo: pageNo.value })
})

let hideTimer: ReturnType<typeof setTimeout> | undefined
// 唤醒顶栏：显示并重置隐藏计时
function pokeBar() {
  showBar.value = true
  clearTimeout(hideTimer)
  hideTimer = setTimeout(() => (showBar.value = false), 2600)
}
// 切换顶栏：可见则立即隐藏，隐藏则唤醒
function toggleBar() {
  if (showBar.value) {
    showBar.value = false
    clearTimeout(hideTimer)
  } else {
    pokeBar()
  }
}

onMounted(async () => {
  comicId = Number(route.params.comicId ?? 0)
  chapterId.value = Number(route.params.chapterId ?? 0)
  loadSettings()
  chapters.value = await getChapters(comicId)
  await loadChapter(chapterId.value)

  // 续读：从历史恢复上次阅读页码
  const list = await getHistory()
  const rec = list.find((h) => h.comicId === comicId && h.chapterId === chapterId.value)
  if (rec && rec.pageNo <= total.value) {
    pageNo.value = rec.pageNo
    if (isVertical.value) scrollToPage(rec.pageNo)
  }
  if (rec) upsertHistory({ comicId, chapterId: chapterId.value, pageNo: rec.pageNo })

  // 键盘事件（桌面浏览器）
  window.addEventListener('keydown', onKey)
  pokeBar()
})

onBeforeUnmount(() => {
  window.removeEventListener('keydown', onKey)
  clearTimeout(measureTimer)
  clearTimeout(hideTimer)
})
</script>


<template>
  <Layout>
    <div
      class="reader"
      :class="{ light: theme === 'light', vertical: isVertical }"
      @click="onTapZone"
      @touchstart="onTouchStart"
      @touchend="onTouchEnd"
      @touchcancel="cancelSwipe"
      @pointerdown="onPointerDown"
      @pointerup="onPointerUp"
      @pointercancel="cancelSwipe"
      @pointerleave="cancelSwipe"
    >
      <!-- 顶栏 -->
      <div class="topbar" :class="{ hide: !showBar }" @click.stop>
        <div class="tb-left">
          <button class="icon-btn u-button" @click="router.back()" aria-label="返回">←</button>
          <span class="tb-title u-span">{{ chapter?.title }}</span>
        </div>
        <div class="tb-right">
          <button class="ghost-sm u-button" :disabled="!hasPrev" @click="prevChapter">上一章</button>
          <button class="ghost-sm u-button" :disabled="!hasNext" @click="nextChapter">下一章</button>
          <button class="icon-btn u-button" title="设置" aria-label="设置" @click="showSettings = !showSettings">⚙</button>
          <button class="icon-btn u-button" title="目录" aria-label="目录" @click="showMenu = !showMenu">☰</button>
        </div>
      </div>

      <!-- 设置面板：遮罩点击关闭；面板自身 @click.stop 拦住冒泡，不关闭 -->
      <div v-if="showSettings" class="settings-mask" @click.stop="showSettings = false">
        <div class="settings-panel" @click.stop>
          <div class="u-h3">阅读设置</div>

          <div class="set-row">
            <span class="set-label u-span">阅读模式</span>
            <div class="seg">
              <button class="seg-btn u-button" :class="{ on: mode === 'horizontal' }" @click="setMode('horizontal')">左右滑动</button>
              <button class="seg-btn u-button" :class="{ on: mode === 'vertical' }" @click="setMode('vertical')">竖排连播</button>
            </div>
          </div>

          <div class="set-row">
            <span class="set-label u-span">背景主题</span>
            <div class="seg">
              <button class="seg-btn u-button" :class="{ on: theme === 'dark' }" @click="setTheme('dark')">深色</button>
              <button class="seg-btn u-button" :class="{ on: theme === 'light' }" @click="setTheme('light')">浅色</button>
            </div>
          </div>

          <div class="set-hint u-p">
            {{ mode === 'horizontal' ? '左右滑动或点击两侧翻页；上下滑动不切页' : '上下滑动连续浏览本章全部页' }}
          </div>
        </div>
      </div>

      <!-- 章节目录抽屉：遮罩点击关闭；面板自身 @click.stop 拦住冒泡，不关闭 -->
      <div v-if="showMenu" class="menu-mask" @click.stop="showMenu = false">
        <div class="chapter-menu" @click.stop>
          <div class="u-h3">章节目录</div>
          <button
            v-for="(c, i) in chapters"
            :key="c.id"
            class="menu-item u-button"
            :class="{ on: c.id === chapterId }"
            @click="goChapter(c.id)"
          >
            <span class="u-span">{{ i + 1 }}. {{ c.title }}</span>
          </button>
        </div>
      </div>

      <!-- ============ 竖排连播模式 ============ -->
      <div v-if="isVertical" class="stage vertical-stage">
        <div v-if="loading" class="center-hint">加载章节中…</div>
        <!-- 源站这一话没有图片数据（page 清单为空）：给明确提示，别让人以为是加载中 -->
        <div v-else-if="pages.length === 0" class="empty-chapter">
          <div class="main u-p">该话在源站暂无内容</div>
          <div class="sub u-p">源站这一话没有图片数据，换一话看看</div>
          <div class="empty-btns">
            <button class="btn ghost u-button" :disabled="!hasPrev" @click="prevChapter">上一章</button>
            <button class="btn u-button" :disabled="!hasNext" @click="nextChapter">下一章</button>
          </div>
        </div>
        <!-- 竖排连播的滚动容器：原生 div + overflow（CSS 的 .pages-scroll 控制），
             跳页用 scrollIntoView 定位到对应页块的 id。 -->
        <div
          v-else
          id="pages-scroll"
          class="pages-scroll"
          @scroll="onScroll"
        >
          <div v-if="imgLoading && pageNo === 1" class="page-loading">
            <div class="spinner"></div>
            <span class="u-span">图片加载中…</span>
          </div>

          <div class="pages-stream">
            <div
              v-for="(p, i) in pages"
              :id="`pb${p.pageNo}`"
              :key="i"
              class="page-block"
              :data-page="p.pageNo"
            >
              <!-- 竖排的页图：宽度定、高度按原图比例自适应（CSS 的 .page-img 控制） -->
              <img
                :src="p.imageUrl"
                class="page-img u-img"
                loading="lazy"
                @load="onImgLoad"
              />
              <div v-if="pages.length > 1" class="page-indicator">{{ p.pageNo }}</div>
            </div>
          </div>

          <!-- 竖排模式的收尾块：**排在滚动流末尾**（CSS 里 `.vertical-stage .end-bar` 覆盖掉 fixed），
               否则浮层会盖住最后一页（实测重叠 90px）。按钮不带左右箭头，靠宽度保证文字一行显示全。
               ⚠️ **不挂 `v-if="pageNo === total"`**（2026-10-09 修）：pageNo 由滚动测量推导，滚到底的
               那一刻才变 total → 收尾块这时才插入滚动流 → 内容突然变长（+160px）但滚动位置不动 →
               收尾块停在视口外，**要再滚一次才看得到**（用户报「下滑到底按钮显示不出来」）。
               它本来就排在最后一张图下方，不滚到那里根本看不到，常驻零副作用。 -->
          <div class="end-bar">
            <div class="u-p">— 本章完 —</div>
            <div class="end-btns">
              <button class="btn ghost u-button" :disabled="!hasPrev" @click="prevChapter">上一章</button>
              <button class="btn u-button" :disabled="!hasNext" @click="nextChapter">下一章</button>
            </div>
          </div>
        </div>
      </div>

      <!-- ============ 左右滑动模式 ============ -->
      <div v-else class="stage horizontal-stage">
        <div v-if="loading" class="center-hint">加载章节中…</div>
        <div v-else-if="pages.length === 0" class="empty-chapter">
          <div class="main u-p">该话在源站暂无内容</div>
          <div class="sub u-p">源站这一话没有图片数据，换一话看看</div>
          <div class="empty-btns">
            <button class="btn ghost u-button" :disabled="!hasPrev" @click="prevChapter">上一章</button>
            <button class="btn u-button" :disabled="!hasNext" @click="nextChapter">下一章</button>
          </div>
        </div>
        <template v-else>
          <div class="page-wrap">
            <!-- aspectFit = 等比缩放不裁剪（对应原来原生 img + max-width/max-height 的语义） -->
            <img
              v-if="isNear(pageNo)"
              :src="pages[pageNo - 1]?.imageUrl"
              class="page-img u-img"
              :class="{ hidden: imgLoading }"
              @load="onImgLoad"
             />
            <div v-if="imgLoading" class="page-loading">
              <div class="spinner"></div>
              <span class="u-span">图片加载中…</span>
            </div>
          </div>

          <div class="zone-hint prev" :class="{ show: pageNo > 1 }">‹</div>
          <div class="zone-hint next" :class="{ show: pageNo < total }">›</div>

          <!-- 横向模式：无滚动可排，收尾块仍是浮层（底栏之上），按钮同样去掉箭头 -->
          <div v-if="pageNo === total" class="end-bar">
            <div class="u-p">— 本章完 —</div>
            <div class="end-btns">
              <button class="btn ghost u-button" :disabled="!hasPrev" @click="prevChapter">上一章</button>
              <button class="btn u-button" :disabled="!hasNext" @click="nextChapter">下一章</button>
            </div>
          </div>
        </template>
      </div>

      <!-- 底部进度条：可点击、也可**拖动**跳页（拖动中显示预览页号，松手才翻页）。
           ⚠️ 只绑 touch + mouse：uni 的模板编译器**不认 `@pointerdown` 这类 pointer 事件**（静默丢弃，
              实测处理器根本不触发；根节点上那套 pointer 翻页绑定同理是死的）。
              触摸覆盖触屏设备，鼠标覆盖桌面端。
           ⚠️ 每个事件都要 `.stop`：否则会冒泡到根节点，触发阅读器自己的点击显隐/左右滑动翻页。 -->
      <div class="bottombar" :class="{ hide: !showBar }" @click.stop>
        <div
          id="progress-track"
          class="progress-track"
          :class="{ seeking }"
          @touchstart.stop="beginSeek"
          @touchmove.stop="updateSeek"
          @touchend.stop="endSeek"
          @touchcancel.stop="endSeek"
          @mousedown.stop="beginSeek"
        >
          <div class="progress-fill" :style="{ width: progress + '%' }"></div>
          <!-- 拖动手柄：给个明确的"可以拖"的视觉提示 -->
          <div class="progress-thumb" :style="{ left: progress + '%' }"></div>
        </div>
        <span class="page-no u-span">{{ shownPage }} / {{ total }}</span>
      </div>
    </div>
  </Layout>
</template>

<style scoped>
.reader {
  --reader-bg: #141210;
  --reader-text: #fff;
  /* 悬浮底栏的高度（实测 45px；阅读器没有 safe-area 处理）。图片满幅、栏盖在图上，
     这个值只用于**给内容留出不被栏压住的边距**（竖排收尾块的下边距）。 */
  --bb-h: 45px;
  position: fixed;
  top: 0; right: 0; bottom: 0; left: 0;
  background: var(--reader-bg);
  z-index: 200;
  user-select: none;
  -webkit-user-select: none;
  overflow: hidden;
  transition: background 0.25s;
}
/* 竖排模式：自身作为滚动容器 */
.reader.vertical {
  overflow-y: auto;
  -webkit-overflow-scrolling: touch;
  touch-action: pan-y;
}
.reader.light {
  --reader-bg: #f5f4f0;
  --reader-text: #1a1a1a;
}

/* 顶栏 */
.topbar {
  position: fixed;
  top: 0; left: 0; right: 0;
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 10px 14px;
  /* 透明化悬浮：只留一层很淡的渐变保证文字可读，漫画从下面透出来（原 0.55 偏重，看着像一块横条） */
  background: linear-gradient(rgba(0,0,0,0.34), rgba(0,0,0,0));
  z-index: 5;
  transition: opacity 0.25s, transform 0.25s;
}
.topbar.hide { opacity: 0; transform: translateY(-100%); pointer-events: none; }
.reader.light .topbar { background: linear-gradient(rgba(0,0,0,0.06), transparent); }
.tb-left, .tb-right { display: flex; align-items: center; gap: 10px; }
/* 右组（上一章 / 下一章 / ⚙ / ☰）**固定不收缩** —— 否则长标题把它们挤成两行
   （2026-10-09 用户报）。剩余宽度全归左边标题，超长时以省略号收尾。
   gap 收到 6px（组内间距）给标题多腾一点宽度。 */
.tb-right { flex: 0 0 auto; gap: 6px; }
.tb-left { flex: 1 1 auto; min-width: 0; }
.tb-title {
  color: #fff; font-weight: 600; font-size: 15px; text-shadow: 0 1px 3px rgba(0,0,0,0.6);
  /* 标题跟随可用宽度、超长省略（min-width: 0 是让 flex 项能缩到内容宽以下的前提） */
  min-width: 0;
  overflow: hidden; text-overflow: ellipsis; white-space: nowrap;
}
.reader.light .tb-title { color: #1a1a1a; text-shadow: none; }
.icon-btn {
  border: none;
  background: rgba(255,255,255,0.14);
  color: #fff;
  width: 36px; height: 36px;
  border-radius: 50%;
  font-size: 17px;
  cursor: pointer;
  backdrop-filter: blur(4px);
  transition: background 0.2s, color 0.2s;
}
.icon-btn:hover { background: rgba(255,255,255,0.28); }
.reader.light .icon-btn { background: rgba(0,0,0,0.08); color: #1a1a1a; }
.reader.light .icon-btn:hover { background: rgba(0,0,0,0.16); }
.ghost-sm {
  border: 1px solid rgba(255,255,255,0.35);
  background: rgba(255,255,255,0.1);
  color: #fff;
  /* 横向内边距 14 → 10：给长标题腾宽度（2026-10-09），同时保持「上一章」一行显示 */
  padding: 6px 10px;
  border-radius: 999px;
  font-size: 13px;
  cursor: pointer;
  transition: background 0.2s, color 0.2s, border-color 0.2s;
}
.ghost-sm:disabled { opacity: 0.35; cursor: not-allowed; }
.ghost-sm:not(:disabled):hover { background: rgba(255,255,255,0.22); }
.reader.light .ghost-sm { border-color: rgba(0,0,0,0.3); background: rgba(0,0,0,0.06); color: #1a1a1a; }
.reader.light .ghost-sm:not(:disabled):hover { background: rgba(0,0,0,0.12); }

/* 设置面板 */
.settings-mask {
  position: fixed;
  top: 0; right: 0; bottom: 0; left: 0;
  background: rgba(0,0,0,0.35);
  z-index: 6;
}
.settings-panel {
  position: fixed;
  top: 60px;
  right: 14px;
  width: min(280px, 88vw);
  background: var(--reader-bg);
  color: var(--reader-text);
  border-radius: 14px;
  padding: 18px 16px;
  box-shadow: 0 12px 40px rgba(0,0,0,0.5);
  z-index: 7;
}
.reader.light .settings-panel { box-shadow: 0 12px 40px rgba(0,0,0,0.2); }
.settings-panel .u-h3 { margin: 0 0 16px; font-size: 15px; }
.set-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 10px;
  padding: 8px 0;
}
.set-label { font-size: 14px; }
.seg {
  display: flex;
  background: rgba(255,255,255,0.12);
  border-radius: 999px;
  padding: 3px;
}
.reader.light .seg { background: rgba(0,0,0,0.08); }
.seg-btn {
  border: none;
  background: transparent;
  color: inherit;
  padding: 6px 12px;
  border-radius: 999px;
  font-size: 13px;
  cursor: pointer;
  opacity: 0.7;
  transition: background 0.2s, color 0.2s, opacity 0.2s;
}
.seg-btn.on { background: var(--primary); color: #fff; opacity: 1; }
.seg-btn:not(.on):hover { opacity: 1; background: rgba(128,128,128,0.2); }
.set-hint { margin: 14px 0 0; font-size: 12px; opacity: 0.55; line-height: 1.5; }

/* 目录抽屉 */
.menu-mask {
  position: fixed;
  top: 0; right: 0; bottom: 0; left: 0;
  background: rgba(0,0,0,0.45);
  z-index: 6;
}
.chapter-menu {
  position: fixed;
  top: 0; right: 0; bottom: 0;
  /* 收窄（2026-10-07 用户反馈「几乎把整个页面都占掉」）：原来 min(320px, 85vw) 在 393px
     视口下就是 320px = **占屏 81%**；现在 min(240px, 66vw) → 240px ≈ 61%，
     仍是抽屉形态，长标题（如「1. 第2回官方人气投票结果」）放不下就换行。 */
  width: min(240px, 66vw);
  background: var(--card);
  padding: 18px 10px;
  overflow-y: auto;
  z-index: 7;
  box-shadow: -8px 0 24px rgba(0,0,0,0.35);
}
.reader.light .chapter-menu { box-shadow: -8px 0 24px rgba(0,0,0,0.12); }
.chapter-menu .u-h3 { margin: 0 0 12px; font-size: 16px; }
.menu-item {
  display: flex;
  justify-content: space-between;
  align-items: center;
  width: 100%;
  text-align: left;
  border: none;
  background: transparent;
  padding: 10px 10px;
  border-radius: 8px;
  font-size: 14px;
  cursor: pointer;
  color: var(--text);
}
.menu-item:hover { background: var(--primary-soft); }
.menu-item.on { background: var(--primary); color: #fff; }

/* 阅读区：**吃满全高**，两根栏以半透明形式悬浮在图片之上（2026-10-07 用户要求
   「顶栏和底栏的背景做成悬浮在漫画上的透明化显示，否则看起来突出一块不美观」）。
   早先为了"不遮住图片"改成让位（图片夹在两根栏之间）→ 图片变小、两根栏像两块突出的横条；
   现在改为：图片满幅 + 栏背景透明化（栏里只有文字/按钮/进度条，图片从下面透出来）。
   `--bb-h` 仍用于竖排收尾块的下边距，避免按钮压在悬浮底栏下面。 */
.stage {
  position: absolute;
  top: 0;
  bottom: 0;
  left: 0;
  right: 0;
}
.horizontal-stage {
  display: flex;
  align-items: center;
  justify-content: center;
}
.center-hint { color: #bbb; font-size: 15px; text-align: center; padding: 60px; }
.reader.light .center-hint { color: #888; }

/* 源站该话没有图片数据（page 清单为空）时的空状态 */
.empty-chapter { display: flex; flex-direction: column; align-items: center; gap: 6px; padding: 70px 24px; text-align: center; }
.empty-chapter .main { margin: 0; font-size: 15px; color: #ddd; }
.empty-chapter .sub { margin: 0; font-size: 13px; color: #999; }
.empty-chapter .empty-btns { display: flex; gap: 12px; margin-top: 14px; }
.reader.light .empty-chapter .main { color: #444; }
.reader.light .empty-chapter .sub { color: #888; }

.page-loading {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 12px;
  color: #bbb;
  padding: 60px;
}
.reader.light .page-loading { color: #888; }
.spinner {
  width: 34px; height: 34px;
  border: 3px solid rgba(255,255,255,0.2);
  border-top-color: var(--primary);
  border-radius: 50%;
  animation: spin 0.8s linear infinite;
}
@keyframes spin { to { transform: rotate(360deg); } }

/* ---- 横向模式：单张居中 ---- */
.page-wrap { position: relative; max-width: 100vw; max-height: 100vh; }
/* <uni-image> 无固有尺寸 → 必须给显式方框（等于原来的 max 尺寸）；
   配 aspectFit = 在这个框内等比缩放、不裁剪，视觉效果与原实现一致 */
.horizontal-stage .page-img {
  display: block;
  /* 满幅：手机竖屏下图片按**宽度**铺满，左右不留黑边（原 92vw 会各留 4vw ≈ 16px）。
     桌面等「高度受限」的场景仍由 min() 第二项决定宽度，行为不变。
     高度直接吃满视口 —— 上下那两段由**半透明悬浮栏**盖着，图片能透出来。 */
  width: min(100vw, calc(100vh * 0.705));
  height: 100vh;
  border-radius: 4px;
  box-shadow: 0 10px 40px rgba(0,0,0,0.5);
}
.page-img.hidden { visibility: hidden; position: absolute; }

.zone-hint {
  position: absolute;
  top: 50%;
  transform: translateY(-50%);
  width: 46px; height: 84px;
  border-radius: 12px;
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 30px;
  color: #fff;
  background: rgba(255,255,255,0.08);
  opacity: 0;
  transition: opacity 0.2s;
  pointer-events: none;
}
.zone-hint.prev { left: 14px; }
.zone-hint.next { right: 14px; }
.zone-hint.show { opacity: 1; }
.reader.light .zone-hint { color: #1a1a1a; background: rgba(0,0,0,0.06); }

/* ---- 竖排模式：一连串图片 ---- */
.vertical-stage { padding-top: 0; overflow: visible; }
/* 竖排连播的滚动容器：absolute 铺满 stage（stage 已是全高，两根悬浮栏盖在上面）。 */
.pages-scroll { position: absolute; top: 0; left: 0; right: 0; bottom: 0; overflow-y: auto; }
/* 隐掉滚动条：桌面 Chrome 下滚动条会实占 8px 宽，把竖排图片挤窄、右边露出黑边。
   阅读区是全幅暗色层，滚动条没有意义 —— 进度由底部进度条反映。 */
.pages-scroll { scrollbar-width: none; }
.pages-scroll::-webkit-scrollbar { width: 0; height: 0; display: none; }
.pages-stream {
  display: flex;
  flex-direction: column;
  align-items: center;
  width: 100%;
}
.page-block { position: relative; width: 100%; display: flex; justify-content: center; }
/* ⚠️ 必须给**宽度**：<uni-image> 没有固有尺寸，width:auto 会收缩成 0（整屏无图）。
   配 widthFix：uni 按「offsetWidth ÷ 原图宽高比」算出高度。 */
.vertical-stage .page-img {
  display: block;
  /* 满幅：同横向模式，左右不留黑边（原 96vw 各留 2vw）。720px 上限对桌面生效。 */
  width: min(100vw, 720px);
  height: auto;
  border-radius: 2px;
}
.page-indicator {
  position: absolute;
  right: 12px; bottom: 8px;
  color: #fff;
  font-size: 12px;
  background: rgba(0,0,0,0.35);
  padding: 2px 8px;
  border-radius: 999px;
  pointer-events: none;
}
.reader.light .page-indicator { background: rgba(255,255,255,0.6); color: #1a1a1a; }

/* 章末引导 */
.end-bar {
  position: fixed;
  bottom: 56px;
  left: 50%;
  transform: translateX(-50%);
  text-align: center;
  color: #ddd;
  z-index: 4;
}
/* ⚠️ 竖排连播：收尾块必须**排进滚动流**（覆盖上面的 fixed）——
   浮层会压在最后一页图片上（实测重叠 90px，2026-10-07 用户反馈）。
   横排没有滚动空间可排，仍保持浮层（在底栏之上）。 */
.vertical-stage .end-bar {
  position: static;
  bottom: auto;
  left: auto;
  transform: none;
  /* 下边距留出悬浮底栏的高度，否则「上一章/下一章」会压在底栏下面点不到 */
  padding: 20px 0 calc(26px + var(--bb-h));
}
.reader.light .end-bar { color: #555; }
.end-bar .u-p { margin: 0 0 10px; font-size: 14px; letter-spacing: 2px; }
.end-btns { display: flex; gap: 10px; justify-content: center; }
/* 按钮：加宽 + 不换行，保证「上一章 / 下一章」一行显示完整（原来 94×58 = 被挤成两行） */
.end-btns .btn {
  min-width: 140px;
  white-space: nowrap;
}

/* 底部进度 */
.bottombar {
  position: fixed;
  bottom: 0; left: 0; right: 0;
  display: flex;
  align-items: center;
  gap: 12px;
  padding: 10px 16px 14px;
  /* 同顶栏：透明化悬浮，漫画透出来（原 0.6 偏重） */
  background: linear-gradient(rgba(0,0,0,0), rgba(0,0,0,0.34));
  z-index: 5;
  transition: opacity 0.25s, transform 0.25s;
}
.bottombar.hide { opacity: 0; transform: translateY(100%); pointer-events: none; }
.reader.light .bottombar { background: linear-gradient(transparent, rgba(0,0,0,0.1)); }
.progress-track {
  flex: 1;
  height: 5px;
  border-radius: 3px;
  /* 悬浮在图上，底色比原来略实一点保证看得见（原 0.22 在浅色漫画上几乎看不见） */
  background: rgba(255,255,255,0.3);
  cursor: pointer;
  /* 拖动热区放大：5px 高的轨道太细，手指按不准 —— 用伪元素把上下各撑 10px（视觉不变） */
  position: relative;
  touch-action: none;
}
.progress-track::before {
  content: '';
  position: absolute;
  top: -10px;
  bottom: -10px;
  left: 0;
  right: 0;
}
/* 拖动手柄：平时半透明小圆点，拖动中放大 —— 让人一眼看出这条能拖 */
.progress-thumb {
  position: absolute;
  top: 50%;
  width: 12px;
  height: 12px;
  margin-left: -6px;
  margin-top: -6px;
  border-radius: 50%;
  background: #fff;
  box-shadow: 0 1px 4px rgba(0,0,0,0.5);
  transition: transform 0.15s;
}
.progress-track.seeking .progress-thumb { transform: scale(1.35); }
.reader.light .progress-track { background: rgba(0,0,0,0.15); }
.progress-fill {
  height: 100%;
  border-radius: 3px;
  background: linear-gradient(90deg, var(--primary), var(--accent));
  transition: width 0.15s;
}
.page-no { color: #fff; font-size: 13px; min-width: 60px; text-align: right; text-shadow: 0 1px 3px rgba(0,0,0,0.75); }
.reader.light .page-no { color: #1a1a1a; text-shadow: none; }

/* 两个弹层（设置 / 目录）的出现动画 —— 用 CSS 动画表达（离开时直接移除）。 */
.settings-mask, .menu-mask { animation: fade-in 0.2s ease; }
@keyframes fade-in {
  from { opacity: 0; }
  to { opacity: 1; }
}

/* ==================== 网页版（.mode-web，2026-10-10） ====================
   阅读器是全屏 fixed 层（两种形态都盖住顶栏，沉浸阅读）。桌面加宽正文列 ——
   竖排图片宽度上限 720px → 880px（手机端不变；横排本来就是「高度受限」，无需改）。 */
.mode-web .vertical-stage .page-img { width: min(100vw, 880px); }
</style>
