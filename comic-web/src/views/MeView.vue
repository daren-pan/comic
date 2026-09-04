<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import { getFavorites, getHistoryWithDetail, removeHistory, isLoggedIn } from '../api'
import type { Comic, HistoryEntry } from '../types'

const router = useRouter()
const favorites = ref<Comic[]>([])
const history = ref<(HistoryEntry & { comic?: Comic; chapterTitle?: string })[]>([])
const loaded = ref(false)
const tab = ref<'history' | 'favorites'>('history')
const logged = ref(isLoggedIn())

function fmtTime(iso: string): string {
  const d = new Date(iso)
  const pad = (n: number) => String(n).padStart(2, '0')
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())} ${pad(d.getHours())}:${pad(d.getMinutes())}`
}

async function refresh() {
  const [favs, his] = await Promise.all([
    logged.value ? getFavorites() : Promise.resolve([]),
    getHistoryWithDetail(),
  ])
  favorites.value = favs
  history.value = his
  loaded.value = true
}

onMounted(refresh)

async function onRemove(comicId: number) {
  await removeHistory(comicId)
  history.value = history.value.filter((h) => h.comicId !== comicId)
}

function continueRead(h: HistoryEntry) {
  router.push(`/reader/${h.comicId}/${h.chapterId}`)
}
</script>

<template>
  <div>
    <h2 class="section-title">我的书架</h2>

    <div class="tabs">
      <button :class="{ on: tab === 'history' }" @click="tab = 'history'">最近阅读</button>
      <button :class="{ on: tab === 'favorites' }" @click="tab = 'favorites'">我的收藏</button>
    </div>

    <div v-if="!loaded" class="empty">加载中…</div>

    <!-- 最近阅读 -->
    <div v-else-if="tab === 'history'">
      <div v-if="history.length === 0" class="empty">还没有阅读记录，去首页找一本看看吧</div>
      <div v-else class="list">
        <div v-for="h in history" :key="h.comicId" class="row" @click="continueRead(h)">
          <img class="row-cover" :src="h.comic?.cover" :alt="h.comic?.title" />
          <div class="row-main">
            <h4>{{ h.comic?.title }}</h4>
            <p class="row-sub">{{ h.chapterTitle }}</p>
            <p class="row-sub dim">读到第 {{ h.pageNo }} 页 · {{ fmtTime(h.readAt) }}</p>
          </div>
          <div class="row-actions" @click.stop>
            <button class="btn ghost sm" @click="continueRead(h)">续读</button>
            <button class="btn ghost sm danger" @click="onRemove(h.comicId)">删除</button>
          </div>
        </div>
      </div>
    </div>

    <!-- 收藏 -->
    <div v-else>
      <div v-if="!logged" class="fav-login">
        <p>收藏需要登录，登录后可跨设备同步</p>
        <button class="btn" @click="router.push('/login')">去登录</button>
      </div>
      <div v-else-if="favorites.length === 0" class="empty">还没有收藏，详情页点「收藏」即可加入书架</div>
      <div v-else class="fav-grid">
        <div v-for="c in favorites" :key="c.id" class="fav-item" @click="router.push(`/comic/${c.id}`)">
          <img :src="c.cover" :alt="c.title" />
          <p>{{ c.title }}</p>
          <span>{{ c.chapterCount }} 话</span>
        </div>
      </div>
    </div>
  </div>
</template>

<style scoped>
.tabs { display: flex; gap: 8px; margin-bottom: 16px; }
.tabs button {
  border: 1px solid var(--border);
  background: #fff;
  padding: 7px 20px;
  border-radius: 999px;
  font-size: 14px;
  cursor: pointer;
  font-weight: 600;
  color: var(--text-2);
}
.tabs button.on { background: var(--primary); border-color: var(--primary); color: #fff; }

.list { display: flex; flex-direction: column; gap: 10px; }
.row {
  display: flex;
  align-items: center;
  gap: 14px;
  background: #fff;
  border: 1px solid var(--border);
  border-radius: 12px;
  padding: 10px 14px;
  cursor: pointer;
  transition: all 0.15s;
}
.row:hover { border-color: var(--primary); box-shadow: var(--shadow-hover); transform: translateY(-1px); }
.row-cover { width: 54px; height: 72px; border-radius: 8px; object-fit: cover; }
.row-main { flex: 1; min-width: 0; }
.row-main h4 { margin: 0; font-size: 15px; }
.row-sub { margin: 2px 0 0; font-size: 13px; color: var(--primary); }
.row-sub.dim { color: var(--text-2); }
.row-actions { display: flex; gap: 8px; }
.btn.sm { padding: 5px 12px; font-size: 13px; }
.btn.danger:hover { border-color: #e23; color: #e23; }

.fav-grid { display: grid; grid-template-columns: repeat(6, 1fr); gap: 14px; }
.fav-login {
  text-align: center;
  background: #fff;
  border: 1px solid var(--border);
  border-radius: 12px;
  padding: 48px 20px;
  color: var(--text-2);
}
.fav-login p { margin: 0 0 16px; font-size: 14px; }
.fav-item {
  background: #fff;
  border-radius: 12px;
  overflow: hidden;
  cursor: pointer;
  box-shadow: var(--shadow);
  transition: all 0.15s;
  text-align: center;
  padding-bottom: 8px;
}
.fav-item:hover { transform: translateY(-3px); box-shadow: var(--shadow-hover); }
.fav-item img { width: 100%; aspect-ratio: 3/4; object-fit: cover; display: block; }
.fav-item p { margin: 6px 0 0; font-size: 13px; font-weight: 600; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; padding: 0 6px; }
.fav-item span { font-size: 12px; color: var(--text-2); }

@media (max-width: 900px) {
  .fav-grid { grid-template-columns: repeat(4, 1fr); }
  .row-actions { flex-direction: column; }
}
@media (max-width: 560px) {
  .fav-grid { grid-template-columns: repeat(3, 1fr); }
}
</style>
