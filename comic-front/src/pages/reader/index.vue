<script setup lang="ts">
// 阅读器（由 comic-web 的 ReaderView 移植）。
//
// ⚠️ 多端适配说明（2026-09-22）：comic-web 的交互全部建立在 H5 API 上，小程序端**全都不可用**：
//   - `PointerEvent`            → 改为 `touchstart/touchend`（小程序/H5 触屏）+ 保留 pointer（H5 桌面鼠标拖拽）
//   - `requestAnimationFrame`   → 改为 `setTimeout` 节流（小程序没有 rAF）
//   - `element.scrollTo`        → 改为 `scroll-view` 的 `scroll-into-view`（小程序普通 view 不能滚）
//   - `getBoundingClientRect`   → 改为 `uni.createSelectorQuery().boundingClientRect`（三端同一套）
//   - `e.clientX`               → 小程序把坐标放在 `e.detail.x`，统一由 `eventX()` 取
//   - `e.currentTarget`         → 进度条点击改为按需量轨道位置（只在点击时量，不是热路径）
// **业务判定规则一字未改**：滑动阈值 60px / 800ms、左右热区各 25%、当前页取"视口中心最近的那页"。
import { computed, nextTick, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { onLoad } from '@dcloudio/uni-app'
import { getChapters, getChapter, getChapterPages, getHistory, upsertHistory } from '../../api'
import { setRoute, useRouter } from '../../utils/router'
import { storage } from '../../utils/storage'
import Layout from '../../components/Layout.vue'
import type { Chapter, PageInfo } from '../../types'

const router = useRouter()
// 路由参数由 uni 的 onLoad(options) 提供（uni 页面栈没有 vue-router 的 params）
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
// 竖排连播的滚动锚点（scroll-view 的 scroll-into-view 目标 id）
const scrollAnchor = ref('')

const chapterIdx = computed(() => chapters.value.findIndex((c) => c.id === chapterId.value))
const hasPrev = computed(() => chapterIdx.value > 0)
const hasNext = computed(() => chapterIdx.value >= 0 && chapterIdx.value < chapters.value.length - 1)
const total = computed(() => pages.value.length)
const progress = computed(() => (total.value ? Math.round((pageNo.value / total.value) * 100) : 0))
const isVertical = computed(() => mode.value === 'vertical')

// 横向模式懒加载：仅当前页与前后各一页真实渲染
function isNear(p: number) {
  return Math.abs(p - pageNo.value) <= 1
}

// ---------------- 跨端坐标 / 测量 ----------------
/** 取事件里的横坐标：H5 是 `clientX`，小程序把坐标放在 `detail.x` */
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

/** 量一个节点的位置（uni 的跨端选择器查询） */
function measureOne(selector: string, cb: (rect: any) => void) {
  uni.createSelectorQuery().select(selector).boundingClientRect((r: any) => cb(r ?? null)).exec()
}

/** 量一批节点的位置 */
function measureAll(selector: string, cb: (rects: any[]) => void) {
  uni
    .createSelectorQuery()
    .selectAll(selector)
    .boundingClientRect((r: any) => cb(Array.isArray(r) ? r : []))
    .exec()
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
  imgLoading.value = true
  if (isVertical.value) scrollToPage(p)
}

// ---------------- 竖排连播：滚动定位 + 当前页推导 ----------------
/** 滚到某页顶部：用 `scroll-into-view`（跨端可用）。同一个 id 连设两次不会触发，
 *  故先清空再于 nextTick 设回 —— uni 的惯用写法。 */
function scrollToPage(p: number) {
  scrollAnchor.value = ''
  nextTick(() => {
    scrollAnchor.value = `pb${p}`
  })
}

let measureTimer: ReturnType<typeof setTimeout> | undefined
/** 滚动回调：节流后量一次（原实现用 requestAnimationFrame 节流，小程序没有 rAF） */
function onScroll() {
  if (!isVertical.value) return
  if (measureTimer) return
  measureTimer = setTimeout(() => {
    measureTimer = undefined
    measureCurrentPage()
  }, 120)
}

/** 取「离视口中心最近的那一页」为当前页 —— 与 comic-web 的判定规则完全一致，
 *  只是把 getBoundingClientRect 换成 uni 的选择器查询（三端同 API）。 */
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
// 小程序 / H5 触屏：touch 事件
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

// 视口宽度：H5 用 window.innerWidth，其他端回退 uni 系统信息
function viewportWidth(): number {
  // #ifdef H5
  return window.innerWidth
  // #endif
  // eslint-disable-next-line no-unreachable
  return uni.getSystemInfoSync().windowWidth
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

/** 点进度条跳页：原来直接读 `e.clientX` 与 `currentTarget.getBoundingClientRect()`（H5 专有），
 *  这里改成**点击时按需量一次轨道位置**（不是热路径，不必缓存）。 */
function onSeek(e: unknown) {
  const x = eventX(e)
  measureOne('#progress-track', (r) => {
    if (!r || !r.width) return
    const ratio = Math.min(1, Math.max(0, (x - r.left) / r.width))
    goPage(Math.max(1, Math.round(ratio * total.value)))
  })
}

function onKey(e: KeyboardEvent) {
  if (e.key === 'Escape') router.push(`/comic/${comicId}`)
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

// uni 页面生命周期：取路由参数 → 登记 web 路径
onLoad((options) => {
  comicId = Number(options?.comicId ?? 0)
  chapterId.value = Number(options?.chapterId ?? 0)
  setRoute(`/reader/${comicId}/${chapterId.value}`, options ?? {})
})

onMounted(async () => {
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

  // 键盘事件仅 H5 有（小程序 / App 无键盘）
  // #ifdef H5
  window.addEventListener('keydown', onKey)
  // #endif
  pokeBar()
})

onBeforeUnmount(() => {
  // #ifdef H5
  window.removeEventListener('keydown', onKey)
  // #endif
  clearTimeout(measureTimer)
  clearTimeout(hideTimer)
})
</script>


<template>
  <Layout>
    <view
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
      <view class="topbar" :class="{ hide: !showBar }" @click.stop>
        <view class="tb-left">
          <button class="icon-btn u-button" @click="router.push(`/comic/${comicId}`)" aria-label="返回">←</button>
          <text class="tb-title u-span">{{ chapter?.title }}</text>
        </view>
        <view class="tb-right">
          <button class="ghost-sm u-button" :disabled="!hasPrev" @click="prevChapter">上一章</button>
          <button class="ghost-sm u-button" :disabled="!hasNext" @click="nextChapter">下一章</button>
          <button class="icon-btn u-button" title="设置" aria-label="设置" @click="showSettings = !showSettings">⚙</button>
          <button class="icon-btn u-button" title="目录" aria-label="目录" @click="showMenu = !showMenu">☰</button>
        </view>
      </view>

      <!-- 设置面板：遮罩点击关闭；面板自身 @click.stop 拦住冒泡，不关闭 -->
      <view v-if="showSettings" class="settings-mask" @click.stop="showSettings = false">
        <view class="settings-panel" @click.stop>
          <view class="u-h3">阅读设置</view>

          <view class="set-row">
            <text class="set-label u-span">阅读模式</text>
            <view class="seg">
              <button class="seg-btn u-button" :class="{ on: mode === 'horizontal' }" @click="setMode('horizontal')">左右滑动</button>
              <button class="seg-btn u-button" :class="{ on: mode === 'vertical' }" @click="setMode('vertical')">竖排连播</button>
            </view>
          </view>

          <view class="set-row">
            <text class="set-label u-span">背景主题</text>
            <view class="seg">
              <button class="seg-btn u-button" :class="{ on: theme === 'dark' }" @click="setTheme('dark')">深色</button>
              <button class="seg-btn u-button" :class="{ on: theme === 'light' }" @click="setTheme('light')">浅色</button>
            </view>
          </view>

          <view class="set-hint u-p">
            {{ mode === 'horizontal' ? '左右滑动或点击两侧翻页；上下滑动不切页' : '上下滑动连续浏览本章全部页' }}
          </view>
        </view>
      </view>

      <!-- 章节目录抽屉：遮罩点击关闭；面板自身 @click.stop 拦住冒泡，不关闭 -->
      <view v-if="showMenu" class="menu-mask" @click.stop="showMenu = false">
        <view class="chapter-menu" @click.stop>
          <view class="u-h3">章节目录</view>
          <button
            v-for="(c, i) in chapters"
            :key="c.id"
            class="menu-item u-button"
            :class="{ on: c.id === chapterId }"
            @click="goChapter(c.id)"
          >
            <text class="u-span">{{ i + 1 }}. {{ c.title }}</text>
          </button>
        </view>
      </view>

      <!-- ============ 竖排连播模式 ============ -->
      <view v-if="isVertical" class="stage vertical-stage">
        <view v-if="loading" class="center-hint">加载章节中…</view>
        <!-- 源站这一话没有图片数据（page 清单为空）：给明确提示，别让人以为是加载中 -->
        <view v-else-if="pages.length === 0" class="empty-chapter">
          <view class="main u-p">该话在源站暂无内容</view>
          <view class="sub u-p">源站这一话没有图片数据，换一话看看</view>
          <view class="empty-btns">
            <button class="btn ghost u-button" :disabled="!hasPrev" @click="prevChapter">← 上一章</button>
            <button class="btn u-button" :disabled="!hasNext" @click="nextChapter">下一章 →</button>
          </view>
        </view>
        <!-- 竖排连播的滚动容器：**小程序里普通 view 不能滚**，必须用 scroll-view
             （原来靠 .reader.vertical 的 overflow-y:auto，那是 H5 专有）。
             跳页用 scroll-into-view 定位到对应页块的 id（跨端可用）。 -->
        <scroll-view
          v-else
          id="pages-scroll"
          class="pages-scroll"
          scroll-y
          :scroll-into-view="scrollAnchor"
          @scroll="onScroll"
        >
          <view v-if="imgLoading && pageNo === 1" class="page-loading">
            <view class="spinner"></view>
            <text class="u-span">图片加载中…</text>
          </view>

          <view class="pages-stream">
            <view
              v-for="(p, i) in pages"
              :id="`pb${p.pageNo}`"
              :key="i"
              class="page-block"
              :data-page="p.pageNo"
            >
              <!-- ⚠️ uni 的 <image> 是 <uni-image> 包装元素（内部靠 div 的 background-image 画图），
                   **没有固有尺寸**，宽高必须由 CSS 给；故竖排用 widthFix（宽度定、高度按原图比例自动算）。
                   aspectFill 是 background-size:cover（按框裁剪），没有显式方框时会渲染不出来。 -->
              <image mode="widthFix"
                :src="p.imageUrl"
                class="page-img u-img"
                lazy-load
                @load="onImgLoad"
              />
              <view v-if="pages.length > 1" class="page-indicator">{{ p.pageNo }}</view>
            </view>
          </view>

          <view v-if="pageNo === total" class="end-bar">
            <view class="u-p">— 本章完 —</view>
            <view class="end-btns">
              <button class="btn ghost u-button" :disabled="!hasPrev" @click="prevChapter">← 上一章</button>
              <button class="btn u-button" :disabled="!hasNext" @click="nextChapter">下一章 →</button>
            </view>
          </view>
        </scroll-view>
      </view>

      <!-- ============ 左右滑动模式 ============ -->
      <view v-else class="stage horizontal-stage">
        <view v-if="loading" class="center-hint">加载章节中…</view>
        <view v-else-if="pages.length === 0" class="empty-chapter">
          <view class="main u-p">该话在源站暂无内容</view>
          <view class="sub u-p">源站这一话没有图片数据，换一话看看</view>
          <view class="empty-btns">
            <button class="btn ghost u-button" :disabled="!hasPrev" @click="prevChapter">← 上一章</button>
            <button class="btn u-button" :disabled="!hasNext" @click="nextChapter">下一章 →</button>
          </view>
        </view>
        <template v-else>
          <view class="page-wrap">
            <!-- aspectFit = 等比缩放不裁剪（对应原来原生 img + max-width/max-height 的语义） -->
            <image mode="aspectFit"
              v-if="isNear(pageNo)"
              :src="pages[pageNo - 1]?.imageUrl"
              class="page-img u-img"
              :class="{ hidden: imgLoading }"
              @load="onImgLoad"
            />
            <view v-if="imgLoading" class="page-loading">
              <view class="spinner"></view>
              <text class="u-span">图片加载中…</text>
            </view>
          </view>

          <view class="zone-hint prev" :class="{ show: pageNo > 1 }">‹</view>
          <view class="zone-hint next" :class="{ show: pageNo < total }">›</view>

          <view v-if="pageNo === total" class="end-bar">
            <view class="u-p">— 本章完 —</view>
            <view class="end-btns">
              <button class="btn ghost u-button" :disabled="!hasPrev" @click="prevChapter">← 上一章</button>
              <button class="btn u-button" :disabled="!hasNext" @click="nextChapter">下一章 →</button>
            </view>
          </view>
        </template>
      </view>

      <!-- 底部进度条 -->
      <view class="bottombar" :class="{ hide: !showBar }" @click.stop>
        <view id="progress-track" class="progress-track" @click="onSeek">
          <view class="progress-fill" :style="{ width: progress + '%' }"></view>
        </view>
        <text class="page-no u-span">{{ pageNo }} / {{ total }}</text>
      </view>
    </view>
  </Layout>
</template>

<style scoped>
.reader {
  --reader-bg: #141210;
  --reader-text: #fff;
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
  background: linear-gradient(rgba(0,0,0,0.55), transparent);
  z-index: 5;
  transition: opacity 0.25s, transform 0.25s;
}
.topbar.hide { opacity: 0; transform: translateY(-100%); pointer-events: none; }
.reader.light .topbar { background: linear-gradient(rgba(0,0,0,0.06), transparent); }
.tb-left, .tb-right { display: flex; align-items: center; gap: 10px; }
.tb-title { color: #fff; font-weight: 600; font-size: 15px; text-shadow: 0 1px 3px rgba(0,0,0,0.6); }
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
  padding: 6px 14px;
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
  width: min(320px, 85vw);
  background: #fff;
  padding: 18px 14px;
  overflow-y: auto;
  z-index: 7;
}
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

/* 阅读区 */
.stage { height: 100%; position: relative; }
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
  width: min(92vw, calc((100vh - 40px) * 0.705));
  height: calc(100vh - 40px);
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
.vertical-stage { padding-top: 40px; overflow: visible; }
/* 竖排连播的滚动容器：absolute 铺满 stage（top:40px 与 .vertical-stage 的 padding-top 对齐，
   避开固定顶栏）。小程序里普通 view 不能滚，滚动必须交给 scroll-view。 */
.pages-scroll { position: absolute; top: 40px; left: 0; right: 0; bottom: 0; }
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
  width: min(96vw, 720px);
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
.reader.light .end-bar { color: #555; }
.end-bar .u-p { margin: 0 0 10px; font-size: 14px; letter-spacing: 2px; }
.end-btns { display: flex; gap: 10px; justify-content: center; }

/* 底部进度 */
.bottombar {
  position: fixed;
  bottom: 0; left: 0; right: 0;
  display: flex;
  align-items: center;
  gap: 12px;
  padding: 10px 16px 14px;
  background: linear-gradient(transparent, rgba(0,0,0,0.6));
  z-index: 5;
  transition: opacity 0.25s, transform 0.25s;
}
.bottombar.hide { opacity: 0; transform: translateY(100%); pointer-events: none; }
.reader.light .bottombar { background: linear-gradient(transparent, rgba(0,0,0,0.1)); }
.progress-track {
  flex: 1;
  height: 5px;
  border-radius: 3px;
  background: rgba(255,255,255,0.22);
  cursor: pointer;
}
.reader.light .progress-track { background: rgba(0,0,0,0.15); }
.progress-fill {
  height: 100%;
  border-radius: 3px;
  background: linear-gradient(90deg, var(--primary), var(--accent));
  transition: width 0.15s;
}
.page-no { color: #fff; font-size: 13px; min-width: 60px; text-align: right; }
.reader.light .page-no { color: #1a1a1a; }

/* 两个弹层（设置 / 目录）的出现动画 —— 原来用 `<transition name="fade">`，
   而**小程序不支持 transition 组件**，改用 CSS 动画（视觉效果一致，离开时直接移除）。 */
.settings-mask, .menu-mask { animation: fade-in 0.2s ease; }
@keyframes fade-in {
  from { opacity: 0; }
  to { opacity: 1; }
}
</style>
