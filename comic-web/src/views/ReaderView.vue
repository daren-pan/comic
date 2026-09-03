<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { getChapters, getChapter, getChapterPages, getHistory, upsertHistory } from '../api'
import type { Chapter, PageInfo } from '../types'

const route = useRoute()
const router = useRouter()
const comicId = Number(route.params.comicId)
const chapterId = Number(route.params.chapterId)

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
const readerEl = ref<HTMLElement>()

const chapterIdx = computed(() => chapters.value.findIndex((c) => c.id === chapterId))
const hasPrev = computed(() => chapterIdx.value > 0)
const hasNext = computed(() => chapterIdx.value >= 0 && chapterIdx.value < chapters.value.length - 1)
const total = computed(() => pages.value.length)
const progress = computed(() => (total.value ? Math.round((pageNo.value / total.value) * 100) : 0))
const isVertical = computed(() => mode.value === 'vertical')

// 横向模式懒加载：仅当前页与前后各一页真实渲染
function isNear(p: number) {
  return Math.abs(p - pageNo.value) <= 1
}

// ---------------- 设置持久化 ----------------
function loadSettings() {
  try {
    const s = JSON.parse(localStorage.getItem('comic_reader_settings') || '{}')
    if (s.theme === 'light' || s.theme === 'dark') theme.value = s.theme
    if (s.mode === 'horizontal' || s.mode === 'vertical') mode.value = s.mode
  } catch {
    /* ignore */
  }
}
function saveSettings() {
  localStorage.setItem('comic_reader_settings', JSON.stringify({ theme: theme.value, mode: mode.value }))
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
    if (m === 'vertical') scrollToPage(pageNo.value)
    else readerEl.value?.scrollTo({ top: 0 })
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
  else readerEl.value?.scrollTo({ top: 0 })
}

function goChapter(id: number) {
  router.replace(`/reader/${comicId}/${id}`)
  loadChapter(id)
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
  else readerEl.value?.scrollTo({ top: 0 })
}

// ---------------- 竖排连播：滚动定位 + 当前页推导 ----------------
function scrollToPage(p: number) {
  const el = readerEl.value
  if (!el) return
  const target = el.querySelector(`[data-page="${p}"]`) as HTMLElement | null
  if (!target) return
  const rel = target.getBoundingClientRect().top - el.getBoundingClientRect().top + el.scrollTop
  el.scrollTo({ top: rel, behavior: 'auto' })
}

let raf = 0
function onScroll() {
  if (!isVertical.value) return
  if (raf) return
  raf = requestAnimationFrame(() => {
    raf = 0
    const el = readerEl.value
    if (!el) return
    const vr = el.getBoundingClientRect()
    const viewCenter = vr.top + vr.height * 0.5
    let best = 1
    let bestDist = Infinity
    el.querySelectorAll('[data-page]').forEach((s) => {
      const r = (s as HTMLElement).getBoundingClientRect()
      const dist = Math.abs(r.top + r.height / 2 - viewCenter)
      if (dist < bestDist) {
        bestDist = dist
        best = Number((s as HTMLElement).dataset.page)
      }
    })
    if (best !== pageNo.value) pageNo.value = best
  })
}

// ---------------- 横向模式：点击热区 + 滑动翻页 ----------------
const SWIPE_THRESHOLD = 60
const swipe = ref({ x: 0, y: 0, t: 0, active: false })
const suppressClick = ref(false)
let suppressTimer: ReturnType<typeof setTimeout> | undefined

function onPointerDown(e: PointerEvent) {
  if (isVertical.value || !e.isPrimary) return
  swipe.value = { x: e.clientX, y: e.clientY, t: Date.now(), active: true }
}
function onPointerUp(e: PointerEvent) {
  if (isVertical.value || !swipe.value.active) return
  const dx = e.clientX - swipe.value.x
  const dy = e.clientY - swipe.value.y
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
function cancelPointer() {
  swipe.value.active = false
}

// 点击处理：
// - 顶栏隐藏时：点击屏幕中心（水平 25%~75%及垂直上方区域）唤醒顶栏
// - 顶栏可见时：点击中心隐藏顶栏；左右 25% 区翻页
// - 竖排模式：点任意位置仅唤醒/隐藏顶栏（不翻页，避免误触）
function onTapZone(e: MouseEvent) {
  if (isVertical.value) {
    toggleBar()
    return
  }
  if (suppressClick.value) {
    suppressClick.value = false
    return
  }
  const x = e.clientX / window.innerWidth
  // 点击顶栏区域（上方）或中心区 → 唤醒/隐藏顶栏
  if (x > 0.25 && x < 0.75) {
    toggleBar()
    return
  }
  // 左右 25% 区 → 翻页
  if (x < 0.25) goPage(pageNo.value - 1)
  else if (x > 0.75) goPage(pageNo.value + 1)
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

onMounted(async () => {
  loadSettings()
  chapters.value = await getChapters(comicId)
  await loadChapter(chapterId)

  // 续读：从历史恢复上次阅读页码
  const list = await getHistory()
  const rec = list.find((h) => h.comicId === comicId && h.chapterId === chapterId)
  if (rec && rec.pageNo <= total.value) {
    pageNo.value = rec.pageNo
    if (isVertical.value) scrollToPage(rec.pageNo)
  }
  if (rec) upsertHistory({ comicId, chapterId, pageNo: rec.pageNo })

  window.addEventListener('keydown', onKey)
  readerEl.value?.addEventListener('scroll', onScroll, { passive: true })
  pokeBar()
})

onBeforeUnmount(() => {
  window.removeEventListener('keydown', onKey)
  readerEl.value?.removeEventListener('scroll', onScroll)
  if (raf) cancelAnimationFrame(raf)
  clearTimeout(hideTimer)
  clearTimeout(tipTimer)
  clearTimeout(suppressTimer)
})

watch(() => route.params.chapterId, (id) => {
  if (id && Number(id) !== chapterId) {
    loadChapter(Number(id))
  }
})
</script>

<template>
  <div
    ref="readerEl"
    class="reader"
    :class="{ light: theme === 'light', vertical: isVertical }"
    @scroll="onScroll"
    @click="onTapZone"
    @pointerdown="onPointerDown"
    @pointerup="onPointerUp"
    @pointercancel="cancelPointer"
    @pointerleave="cancelPointer"
  >
    <!-- 顶栏 -->
    <header class="topbar" :class="{ hide: !showBar }" @click.stop>
      <div class="tb-left">
        <button class="icon-btn" @click="router.push(`/comic/${comicId}`)" aria-label="返回">←</button>
        <span class="tb-title">{{ chapter?.title }}</span>
      </div>
      <div class="tb-right">
        <button class="ghost-sm" :disabled="!hasPrev" @click="prevChapter">上一章</button>
        <button class="ghost-sm" :disabled="!hasNext" @click="nextChapter">下一章</button>
        <button class="icon-btn" title="设置" aria-label="设置" @click="showSettings = !showSettings">⚙</button>
        <button class="icon-btn" title="目录" aria-label="目录" @click="showMenu = !showMenu">☰</button>
      </div>
    </header>

    <!-- 设置面板 -->
    <transition name="fade">
      <div v-if="showSettings" class="settings-mask" @click.self="showSettings = false" @click.stop>
        <div class="settings-panel">
          <h3>阅读设置</h3>

          <div class="set-row">
            <span class="set-label">阅读模式</span>
            <div class="seg">
              <button class="seg-btn" :class="{ on: mode === 'horizontal' }" @click="setMode('horizontal')">左右滑动</button>
              <button class="seg-btn" :class="{ on: mode === 'vertical' }" @click="setMode('vertical')">竖排连播</button>
            </div>
          </div>

          <div class="set-row">
            <span class="set-label">背景主题</span>
            <div class="seg">
              <button class="seg-btn" :class="{ on: theme === 'dark' }" @click="setTheme('dark')">深色</button>
              <button class="seg-btn" :class="{ on: theme === 'light' }" @click="setTheme('light')">浅色</button>
            </div>
          </div>

          <p class="set-hint">
            {{ mode === 'horizontal' ? '左右滑动或点击两侧翻页；上下滑动不切页' : '上下滑动连续浏览本章全部页' }}
          </p>
        </div>
      </div>
    </transition>

    <!-- 章节目录抽屉 -->
    <transition name="fade">
      <div v-if="showMenu" class="menu-mask" @click.self="showMenu = false" @click.stop>
        <div class="chapter-menu">
          <h3>章节目录</h3>
          <button
            v-for="(c, i) in chapters"
            :key="c.id"
            class="menu-item"
            :class="{ on: c.id === chapterId }"
            @click="goChapter(c.id)"
          >
            <span>{{ i + 1 }}. {{ c.title }}</span>
            <small>{{ c.pageCount }}P</small>
          </button>
        </div>
      </div>
    </transition>

    <!-- ============ 竖排连播模式 ============ -->
    <div v-if="isVertical" class="stage vertical-stage">
      <div v-if="loading" class="center-hint">加载章节中…</div>
      <template v-else>
        <div v-if="imgLoading && pageNo === 1" class="page-loading">
          <div class="spinner"></div>
          <span>图片加载中…</span>
        </div>

        <div class="pages-stream">
          <div v-for="(p, i) in pages" :key="i" class="page-block" :data-page="p.pageNo">
            <img
              :src="p.imageUrl"
              :alt="`第${p.pageNo}页`"
              class="page-img"
              loading="lazy"
              @load="onImgLoad"
              draggable="false"
            />
            <div v-if="pages.length > 1" class="page-indicator">{{ p.pageNo }}</div>
          </div>
        </div>

        <div v-if="pageNo === total" class="end-bar">
          <p>— 本章完 —</p>
          <div class="end-btns">
            <button class="btn ghost" :disabled="!hasPrev" @click="prevChapter">← 上一章</button>
            <button class="btn" :disabled="!hasNext" @click="nextChapter">下一章 →</button>
          </div>
        </div>
      </template>
    </div>

    <!-- ============ 左右滑动模式 ============ -->
    <div v-else class="stage horizontal-stage">
      <div v-if="loading" class="center-hint">加载章节中…</div>
      <template v-else>
        <div class="page-wrap">
          <img
            v-if="isNear(pageNo)"
            :src="pages[pageNo - 1]?.imageUrl"
            :alt="`第${pageNo}页`"
            class="page-img"
            :class="{ hidden: imgLoading }"
            @load="onImgLoad"
            draggable="false"
          />
          <div v-if="imgLoading" class="page-loading">
            <div class="spinner"></div>
            <span>图片加载中…</span>
          </div>
        </div>

        <div class="zone-hint prev" :class="{ show: pageNo > 1 }">‹</div>
        <div class="zone-hint next" :class="{ show: pageNo < total }">›</div>

        <div v-if="pageNo === total" class="end-bar">
          <p>— 本章完 —</p>
          <div class="end-btns">
            <button class="btn ghost" :disabled="!hasPrev" @click="prevChapter">← 上一章</button>
            <button class="btn" :disabled="!hasNext" @click="nextChapter">下一章 →</button>
          </div>
        </div>
      </template>
    </div>

    <!-- 底部进度条 -->
    <footer class="bottombar" :class="{ hide: !showBar }" @click.stop>
      <div class="progress-track" @click="(e: MouseEvent) => goPage(Math.max(1, Math.round(((e.clientX - (e.currentTarget as HTMLElement).getBoundingClientRect().left) / (e.currentTarget as HTMLElement).clientWidth) * total)))">
        <div class="progress-fill" :style="{ width: progress + '%' }"></div>
      </div>
      <span class="page-no">{{ pageNo }} / {{ total }}</span>
    </footer>
  </div>
</template>

<style scoped>
.reader {
  --reader-bg: #141210;
  --reader-text: #fff;
  position: fixed;
  inset: 0;
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
  inset: 0;
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
.settings-panel h3 { margin: 0 0 16px; font-size: 15px; }
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
  inset: 0;
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
.chapter-menu h3 { margin: 0 0 12px; font-size: 16px; }
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
.menu-item small { color: inherit; opacity: 0.6; }

/* 阅读区 */
.stage { height: 100%; position: relative; }
.horizontal-stage {
  display: flex;
  align-items: center;
  justify-content: center;
}
.center-hint { color: #bbb; font-size: 15px; text-align: center; padding: 60px; }
.reader.light .center-hint { color: #888; }

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
.horizontal-stage .page-img {
  display: block;
  max-width: min(92vw, calc((100vh - 40px) * 0.705));
  max-height: calc(100vh - 40px);
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
.pages-stream {
  display: flex;
  flex-direction: column;
  align-items: center;
  width: 100%;
}
.page-block { position: relative; width: 100%; display: flex; justify-content: center; }
.vertical-stage .page-img {
  display: block;
  max-width: min(96vw, 720px);
  height: auto;
  width: auto;
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
.end-bar p { margin: 0 0 10px; font-size: 14px; letter-spacing: 2px; }
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

.fade-enter-active, .fade-leave-active { transition: opacity 0.2s; }
.fade-enter-from, .fade-leave-to { opacity: 0; }
</style>
