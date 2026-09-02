<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { getChapter, getChapterPages, getChapters, upsertHistory } from '../api'
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

const chapterIdx = computed(() => chapters.value.findIndex((c) => c.id === chapterId))
const hasPrev = computed(() => chapterIdx.value > 0)
const hasNext = computed(() => chapterIdx.value >= 0 && chapterIdx.value < chapters.value.length - 1)
const total = computed(() => pages.value.length)
const progress = computed(() => (total.value ? Math.round((pageNo.value / total.value) * 100) : 0))

// 懒加载：仅当前页与前后各一页真实渲染（架构方案 §4：图片按需加载 + 预加载）
function isNear(p: number) {
  return Math.abs(p - pageNo.value) <= 1
}

async function loadChapter(id: number) {
  loading.value = true
  chapter.value = await getChapter(comicId, id)
  pages.value = await getChapterPages(comicId, id)
  pageNo.value = 1
  imgLoading.value = true
  loading.value = false
}

function goPage(p: number) {
  if (p < 1 || p > total.value) return
  pageNo.value = p
  imgLoading.value = true
  window.scrollTo({ top: 0 })
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

function onKey(e: KeyboardEvent) {
  if (e.key === 'ArrowLeft') goPage(pageNo.value - 1)
  else if (e.key === 'ArrowRight') goPage(pageNo.value + 1)
  else if (e.key === 'Escape') router.push(`/comic/${comicId}`)
}

function onClickZone(e: MouseEvent) {
  const x = e.clientX / window.innerWidth
  if (x < 0.35) goPage(pageNo.value - 1)
  else if (x > 0.65) goPage(pageNo.value + 1)
}

// 进度记忆：翻页时写入历史（架构方案 §2.2 用户历史；跨端续读）
watch(pageNo, () => {
  if (chapter.value) upsertHistory({ comicId, chapterId: chapter.value.id, pageNo: pageNo.value })
})

let hideTimer: ReturnType<typeof setTimeout> | undefined
function pokeBar() {
  showBar.value = true
  clearTimeout(hideTimer)
  hideTimer = setTimeout(() => (showBar.value = false), 2600)
}

onMounted(async () => {
  chapters.value = await getChapters(comicId)
  await loadChapter(chapterId)

  // 续读：从历史恢复上次阅读页码
  const history = (await import('../api')).getHistory
  const list = await history()
  const rec = list.find((h) => h.comicId === comicId && h.chapterId === chapterId)
  if (rec && rec.pageNo <= total.value) pageNo.value = rec.pageNo
  if (rec) upsertHistory({ comicId, chapterId, pageNo: rec.pageNo })

  window.addEventListener('keydown', onKey)
  pokeBar()
})

onBeforeUnmount(() => {
  window.removeEventListener('keydown', onKey)
  clearTimeout(hideTimer)
})

watch(() => route.params.chapterId, (id) => {
  if (id && Number(id) !== chapterId) {
    loadChapter(Number(id))
  }
})
</script>

<template>
  <div class="reader" @mousemove="pokeBar" @click="onClickZone">
    <!-- 顶栏 -->
    <header class="topbar" :class="{ hide: !showBar }" @click.stop>
      <div class="tb-left">
        <button class="icon-btn" @click="router.push(`/comic/${comicId}`)" aria-label="返回">←</button>
        <span class="tb-title">{{ chapter?.title }}</span>
      </div>
      <div class="tb-right">
        <button class="ghost-sm" :disabled="!hasPrev" @click="prevChapter">上一章</button>
        <button class="ghost-sm" :disabled="!hasNext" @click="nextChapter">下一章</button>
        <button class="icon-btn" @click="showMenu = !showMenu" aria-label="目录">☰</button>
      </div>
    </header>

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

    <!-- 阅读区 -->
    <div class="stage" @mousemove.stop>
      <div v-if="loading" class="center-hint">加载章节中…</div>

      <template v-else>
        <!-- 当前页 -->
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

        <!-- 翻页热区提示 -->
        <div class="zone-hint prev" :class="{ show: pageNo > 1 }">‹</div>
        <div class="zone-hint next" :class="{ show: pageNo < total }">›</div>

        <!-- 章节尾页引导 -->
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
  position: fixed;
  inset: 0;
  background: #141210;
  z-index: 200;
  user-select: none;
  -webkit-user-select: none;
}

/* 顶栏 */
.topbar {
  position: absolute;
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
.tb-left, .tb-right { display: flex; align-items: center; gap: 10px; }
.tb-title { color: #fff; font-weight: 600; font-size: 15px; text-shadow: 0 1px 3px rgba(0,0,0,0.6); }
.icon-btn {
  border: none;
  background: rgba(255,255,255,0.14);
  color: #fff;
  width: 36px; height: 36px;
  border-radius: 50%;
  font-size: 17px;
  cursor: pointer;
  backdrop-filter: blur(4px);
}
.icon-btn:hover { background: rgba(255,255,255,0.28); }
.ghost-sm {
  border: 1px solid rgba(255,255,255,0.35);
  background: rgba(255,255,255,0.1);
  color: #fff;
  padding: 6px 14px;
  border-radius: 999px;
  font-size: 13px;
  cursor: pointer;
}
.ghost-sm:disabled { opacity: 0.35; cursor: not-allowed; }
.ghost-sm:not(:disabled):hover { background: rgba(255,255,255,0.22); }

/* 目录抽屉 */
.menu-mask {
  position: absolute;
  inset: 0;
  background: rgba(0,0,0,0.45);
  z-index: 6;
}
.chapter-menu {
  position: absolute;
  top: 0; right: 0; bottom: 0;
  width: min(320px, 85vw);
  background: #fff;
  padding: 18px 14px;
  overflow-y: auto;
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
.stage {
  height: 100%;
  display: flex;
  align-items: center;
  justify-content: center;
  overflow: hidden;
}
.page-wrap { position: relative; max-width: 100vw; max-height: 100vh; }
.page-img {
  display: block;
  max-width: min(92vw, calc((100vh - 40px) * 0.705));
  max-height: calc(100vh - 40px);
  border-radius: 4px;
  box-shadow: 0 10px 40px rgba(0,0,0,0.5);
}
.page-img.hidden { visibility: hidden; position: absolute; }

.page-loading {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 12px;
  color: #bbb;
  padding: 60px;
}
.spinner {
  width: 34px; height: 34px;
  border: 3px solid rgba(255,255,255,0.2);
  border-top-color: var(--primary);
  border-radius: 50%;
  animation: spin 0.8s linear infinite;
}
@keyframes spin { to { transform: rotate(360deg); } }

.center-hint { color: #bbb; font-size: 15px; }

/* 翻页热区 */
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

/* 章末引导 */
.end-bar {
  position: absolute;
  bottom: 56px;
  left: 50%;
  transform: translateX(-50%);
  text-align: center;
  color: #ddd;
  z-index: 4;
}
.end-bar p { margin: 0 0 10px; font-size: 14px; letter-spacing: 2px; }
.end-btns { display: flex; gap: 10px; justify-content: center; }

/* 底部进度 */
.bottombar {
  position: absolute;
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
.progress-track {
  flex: 1;
  height: 5px;
  border-radius: 3px;
  background: rgba(255,255,255,0.22);
  cursor: pointer;
}
.progress-fill {
  height: 100%;
  border-radius: 3px;
  background: linear-gradient(90deg, var(--primary), var(--accent));
  transition: width 0.15s;
}
.page-no { color: #fff; font-size: 13px; min-width: 60px; text-align: right; }

.fade-enter-active, .fade-leave-active { transition: opacity 0.2s; }
.fade-enter-from, .fade-leave-to { opacity: 0; }
</style>
