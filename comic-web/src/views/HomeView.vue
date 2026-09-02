<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { getCategories, getComics } from '../api'
import type { CategoryCount, Comic } from '../types'
import ComicCard from '../components/ComicCard.vue'

const categories = ref<CategoryCount[]>([])
const hotComics = ref<Comic[]>([])
const latestComics = ref<Comic[]>([])
const catComics = ref<Record<string, Comic[]>>({})
const loaded = ref(false)

function fmtTime(iso: string): string {
  const diff = Date.now() - new Date(iso).getTime()
  const mins = Math.floor(diff / 60000)
  if (mins < 60) return `${Math.max(mins, 1)} 分钟前`
  const hours = Math.floor(mins / 60)
  if (hours < 24) return `${hours} 小时前`
  return `${Math.floor(hours / 24)} 天前`
}

onMounted(async () => {
  categories.value = await getCategories()
  const cats = categories.value.filter((c) => c.name !== '全部').map((c) => c.name)

  const [hot, latest] = await Promise.all([
    getComics({ sort: 'views', pageSize: 8 }),
    getComics({ sort: 'updated', pageSize: 8 }),
  ])
  hotComics.value = hot.items
  latestComics.value = latest.items

  const picks = cats.slice(0, 4)
  const res = await Promise.all(picks.map((c) => getComics({ category: c, pageSize: 5 })))
  picks.forEach((c, i) => (catComics.value[c] = res[i].items))
  loaded.value = true
})
</script>

<template>
  <div>
    <!-- Banner -->
    <section class="banner">
      <div class="banner-inner">
        <h1>聚合全网好漫画<br /><em>一个书架，全网追更</em></h1>
        <p>多源采集 · 指纹去重 · 秒级同步更新 —— 源站一更新，这里几分钟可见</p>
        <div class="banner-badges">
          <span v-for="c in categories.filter((x) => x.name !== '全部').slice(0, 6)" :key="c.name">
            {{ c.name }} {{ c.count }}
          </span>
        </div>
      </div>
    </section>

    <!-- 热门榜 -->
    <h2 class="section-title">🔥 热门榜单</h2>
    <div class="grid">
      <ComicCard v-for="c in hotComics" :key="c.id" :comic="c" />
    </div>

    <!-- 最新更新 -->
    <h2 class="section-title">⚡ 最新更新 <small class="hint">（源站同步 · {{ fmtTime(latestComics[0]?.updatedAt ?? Date.now().toString()) }}内有更新）</small></h2>
    <div class="grid">
      <ComicCard v-for="c in latestComics" :key="c.id" :comic="c" />
    </div>

    <!-- 分类浏览 -->
    <template v-for="cat in categories.filter((x) => x.name !== '全部').slice(0, 4)" :key="cat.name">
      <h2 class="section-title">{{ cat.name }} · 精选</h2>
      <div class="grid grid-5">
        <ComicCard v-for="c in catComics[cat.name]" :key="c.id" :comic="c" />
      </div>
    </template>

    <div v-if="!loaded" class="empty">加载中…</div>
  </div>
</template>

<style scoped>
.banner {
  border-radius: 16px;
  margin-bottom: 8px;
  background:
    radial-gradient(600px 200px at 85% 10%, rgba(255, 176, 46, 0.5), transparent 60%),
    radial-gradient(500px 260px at 10% 90%, rgba(255, 90, 54, 0.4), transparent 55%),
    linear-gradient(120deg, #2b2320, #4a3527);
  color: #fff;
  padding: 34px 30px;
}
.banner-inner { max-width: 640px; }
.banner h1 { font-size: 30px; margin: 0 0 10px; line-height: 1.35; }
.banner h1 em { font-style: normal; color: var(--accent); }
.banner p { margin: 0 0 16px; color: #e8dcd2; font-size: 14px; }
.banner-badges { display: flex; gap: 8px; flex-wrap: wrap; }
.banner-badges span {
  background: rgba(255, 255, 255, 0.14);
  border: 1px solid rgba(255, 255, 255, 0.22);
  padding: 3px 12px;
  border-radius: 999px;
  font-size: 12px;
}

.grid {
  display: grid;
  grid-template-columns: repeat(4, 1fr);
  gap: 16px;
}
.grid-5 { grid-template-columns: repeat(5, 1fr); }
.hint { font-size: 12px; font-weight: 500; color: var(--text-2); margin-left: 4px; }

@media (max-width: 900px) {
  .grid, .grid-5 { grid-template-columns: repeat(3, 1fr); }
}
@media (max-width: 560px) {
  .grid, .grid-5 { grid-template-columns: repeat(2, 1fr); }
  .banner h1 { font-size: 24px; }
}
</style>
