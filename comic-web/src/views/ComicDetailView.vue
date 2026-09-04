<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { getChapter, getChapters, getComic, isFavorite, toggleFavorite, upsertHistory, isLoggedIn } from '../api'
import type { Chapter, Comic } from '../types'

const route = useRoute()
const router = useRouter()
const comicId = Number(route.params.id)

const comic = ref<Comic>()
const chapters = ref<Chapter[]>([])
const fav = ref(false)
const loading = ref(true)
const favNotice = ref(false)

const chapterCount = computed(() => chapters.value.length)

// 章节列表按 orderNo（源站 chapter_order）倒序：最新章节在前，符合阅读习惯。
// 仅在此视图内反向，不改后端接口、不影响阅读器「上一话/下一话」方向。
const sortedChapters = computed(() =>
  [...chapters.value].sort((a, b) => b.orderNo - a.orderNo),
)

onMounted(async () => {
  const [c, chs, f] = await Promise.all([
    getComic(comicId),
    getChapters(comicId),
    isLoggedIn() ? isFavorite(comicId) : Promise.resolve(false),
  ])
  comic.value = c
  chapters.value = chs
  fav.value = f
  loading.value = false
})

async function onFav() {
  // 收藏需要登录；未登录引导去登录页
  if (!isLoggedIn()) {
    favNotice.value = true
    return
  }
  favNotice.value = false
  fav.value = await toggleFavorite(comicId)
}

function gotoLogin() {
  router.push({ path: '/login', query: { redirect: route.fullPath } })
}

async function read(chapter: Chapter) {
  await upsertHistory({ comicId, chapterId: chapter.id, pageNo: 1 })
  router.push(`/reader/${comicId}/${chapter.id}`)
}

function fmtTime(iso: string): string {
  const d = new Date(iso)
  return `${d.getMonth() + 1}月${d.getDate()}日`
}
</script>

<template>
  <div v-if="loading" class="empty">加载中…</div>
  <div v-else-if="comic" class="detail">
    <div class="hero">
      <img class="hero-cover" :src="comic.cover" :alt="comic.title" />
      <div class="hero-info">
        <h1>{{ comic.title }}</h1>
        <p class="hero-meta">
          <span class="chip">{{ comic.category }}</span>
          <span class="chip done" v-if="comic.status === '已完结'">{{ comic.status }}</span>
          <span class="chip hot" v-else>{{ comic.status }}</span>
          <span class="tag" v-for="t in comic.tags" :key="t">#{{ t }}</span>
        </p>
        <p class="hero-line">作者：{{ comic.author }}</p>
        <p class="hero-line">章节：{{ chapterCount }} 话 · 热度 {{ comic.views.toLocaleString() }} · 更新 {{ fmtTime(comic.updatedAt) }}</p>
        <p class="hero-line sources">数据来源：<em v-for="s in comic.sources" :key="s">{{ s }}</em></p>
        <div class="actions">
          <button class="btn" @click="sortedChapters.length && read(sortedChapters[0])">▶ 开始阅读</button>
          <button class="btn ghost" :class="{ active: fav }" @click="onFav">
            {{ fav ? '★ 已收藏' : '☆ 收藏' }}
          </button>
        </div>
        <p v-if="favNotice" class="fav-notice">
          收藏需要登录 — <a href="javascript:;" @click="gotoLogin">去登录</a>，登录后可跨设备同步收藏
        </p>
      </div>
    </div>

    <p class="desc">{{ comic.description }}</p>

    <h2 class="section-title">章节列表（{{ chapterCount }}）</h2>
    <div class="chapters">
      <button
        v-for="(ch, i) in sortedChapters"
        :key="ch.id"
        class="chapter"
        @click="read(ch)"
      >
        <span class="no">{{ i + 1 }}</span>
        <span class="name">{{ ch.title }}</span>
        <span class="pages">{{ ch.pageCount }} 页</span>
      </button>
    </div>
  </div>
</template>

<style scoped>
.hero {
  display: flex;
  gap: 24px;
  background: #fff;
  border-radius: 16px;
  padding: 22px;
  box-shadow: var(--shadow);
}
.hero-cover { width: 190px; height: 253px; border-radius: 10px; object-fit: cover; flex-shrink: 0; box-shadow: 0 6px 18px rgba(0,0,0,0.18); }
.hero-info { flex: 1; min-width: 0; }
.hero-info h1 { margin: 0 0 10px; font-size: 26px; }
.hero-meta { display: flex; align-items: center; gap: 8px; flex-wrap: wrap; margin: 0 0 12px; }
.chip.done { background: #eef0f2; color: #555; }
.chip.hot { background: #fff3e6; color: #b25f00; }
.tag { font-size: 12px; color: var(--text-2); }
.hero-line { margin: 4px 0; color: var(--text-2); font-size: 14px; }
.sources em {
  font-style: normal;
  background: #f0ede8;
  border-radius: 6px;
  padding: 1px 8px;
  font-size: 12px;
  margin-right: 6px;
  color: var(--text-2);
}
.actions { display: flex; gap: 10px; margin-top: 16px; }
.fav-notice {
  margin-top: 10px;
  font-size: 13px;
  color: var(--primary-dark);
  background: var(--primary-soft);
  border-radius: 8px;
  padding: 8px 12px;
}
.fav-notice a { color: var(--primary); font-weight: 700; text-decoration: underline; }

.desc {
  background: #fff;
  border-radius: 12px;
  padding: 14px 18px;
  margin: 16px 0 0;
  color: var(--text-2);
  font-size: 14px;
  line-height: 1.8;
  border-left: 4px solid var(--primary);
}

.chapters {
  display: grid;
  grid-template-columns: repeat(3, 1fr);
  gap: 10px;
}
.chapter {
  display: flex;
  align-items: center;
  gap: 10px;
  background: #fff;
  border: 1px solid var(--border);
  border-radius: 10px;
  padding: 10px 14px;
  cursor: pointer;
  transition: all 0.15s;
  text-align: left;
  font-size: 14px;
}
.chapter:hover { border-color: var(--primary); background: var(--primary-soft); transform: translateY(-1px); }
.no {
  width: 22px; height: 22px;
  border-radius: 6px;
  background: var(--primary-soft);
  color: var(--primary);
  font-weight: 700;
  font-size: 12px;
  display: flex; align-items: center; justify-content: center;
  flex-shrink: 0;
}
.name { flex: 1; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; font-weight: 600; color: var(--text); }
.pages { font-size: 12px; color: #b5aca2; }

@media (max-width: 700px) {
  .hero { flex-direction: column; align-items: center; text-align: center; }
  .hero-meta, .actions { justify-content: center; }
  .chapters { grid-template-columns: 1fr; }
}
</style>
