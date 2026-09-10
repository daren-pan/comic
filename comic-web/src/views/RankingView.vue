<script setup lang="ts">
// 热度排行 —— 按分类分区块，各分类内按热度（views）倒序取前 N 部。
//
// 分类很多（库内 70+ 个标签），为避免一次性发出几十个请求，这里用 IntersectionObserver
// 做「区块进入视口才拉取该分类榜单」的懒加载；分类按作品数从多到少排列，内容多的排前面。
import { onBeforeUnmount, onMounted, ref } from 'vue'
import type { ComponentPublicInstance } from 'vue'
import { getCategories, getComics } from '../api'
import type { CategoryCount, Comic } from '../types'

/** 每个分类榜单展示的作品数 */
const TOP_N = 10
/** 少于该作品数的分类不单独设榜（1~2 部排不出名次） */
const MIN_COUNT = 3

const cats = ref<CategoryCount[]>([])
const lists = ref<Record<string, Comic[]>>({})
const pending = ref<Record<string, boolean>>({})
const ready = ref(false)

const sections = new Map<string, HTMLElement>()
let observer: IntersectionObserver | null = null

async function loadCategory(name: string) {
  if (lists.value[name] || pending.value[name]) return
  pending.value[name] = true
  try {
    const res = await getComics({ category: name, sort: 'views', pageSize: TOP_N })
    lists.value[name] = res.items
  } catch {
    lists.value[name] = []
  } finally {
    pending.value[name] = false
  }
}

/** v-for 的函数式 ref：登记区块元素，进入视口时触发该分类的榜单请求 */
function observeSection(el: Element | ComponentPublicInstance | null, name: string) {
  if (!el || !(el instanceof HTMLElement)) return
  el.dataset.cat = name
  sections.set(name, el)
  observer?.observe(el)
}

function rankClass(i: number): string {
  return i === 0 ? 'top1' : i === 1 ? 'top2' : i === 2 ? 'top3' : ''
}

/** 热度：1 万以上折算为「x.x 万」 */
function fmtHeat(v: number): string {
  if (v >= 10000) return `${(v / 10000).toFixed(1).replace(/\.0$/, '')} 万`
  return String(v)
}

onMounted(async () => {
  // 先建观察器，使区块渲染时的函数式 ref 能立即生效
  observer = new IntersectionObserver(
    (entries) => {
      for (const entry of entries) {
        if (!entry.isIntersecting) continue
        const name = (entry.target as HTMLElement).dataset.cat
        if (name) loadCategory(name)
        observer?.unobserve(entry.target)
      }
    },
    { rootMargin: '240px 0px' },
  )
  sections.forEach((el) => observer?.observe(el))

  try {
    const all = await getCategories()
    cats.value = all
      .filter((c) => c.name !== '全部' && c.count >= MIN_COUNT)
      .sort((a, b) => b.count - a.count)
  } catch {
    cats.value = []
  } finally {
    ready.value = true
  }
})

onBeforeUnmount(() => {
  observer?.disconnect()
  observer = null
  sections.clear()
})
</script>

<template>
  <div>
    <h2 class="section-title">🏆 热度排行</h2>
    <p class="lead">
      按分类分区块，每个分类内按热度（浏览量）从高到低取前 {{ TOP_N }} 部；
      仅收录作品数 ≥ {{ MIN_COUNT }} 的分类，作品多的分类排在前面。
    </p>

    <div v-if="!ready" class="empty">加载中…</div>
    <div v-else-if="cats.length === 0" class="empty">暂无排行数据</div>

    <template v-else>
      <section
        v-for="cat in cats"
        :key="cat.name"
        :ref="(el) => observeSection(el, cat.name)"
        class="block"
      >
        <h3 class="block-head">
          <span class="block-name">{{ cat.name }}</span>
          <span class="block-count">{{ cat.count }} 部</span>
          <RouterLink class="block-more" :to="{ path: '/search', query: { category: cat.name } }">查看全部 ›</RouterLink>
        </h3>

        <div v-if="!lists[cat.name]" class="block-loading">加载中…</div>
        <ol v-else class="rank">
          <li v-for="(c, i) in lists[cat.name]" :key="c.id" class="item">
            <span class="no" :class="rankClass(i)">{{ i + 1 }}</span>
            <RouterLink :to="`/comic/${c.id}`" class="thumb">
              <img :src="c.cover" :alt="c.title" loading="lazy" />
            </RouterLink>
            <div class="info">
              <RouterLink :to="`/comic/${c.id}`" class="name">{{ c.title }}</RouterLink>
              <p class="meta">{{ c.author }}</p>
              <p class="latest">{{ c.latestChapterTitle || '暂无章节' }}</p>
            </div>
            <span class="heat">🔥 {{ fmtHeat(c.views) }}</span>
          </li>
        </ol>
      </section>
    </template>
  </div>
</template>

<style scoped>
.lead { color: var(--text-2); font-size: 14px; margin: -8px 0 18px; }

.block { margin-bottom: 26px; }
.block-head { display: flex; align-items: baseline; gap: 8px; margin: 0 0 10px; font-size: 16px; }
.block-name { font-weight: 800; }
.block-count { font-size: 12px; color: var(--text-2); font-weight: 500; }
.block-more { margin-left: auto; font-size: 12px; color: var(--primary); }
.block-more:hover { text-decoration: underline; }
.block-loading { color: var(--text-2); font-size: 13px; padding: 14px 2px; }

.rank { list-style: none; margin: 0; padding: 0; display: grid; grid-template-columns: repeat(2, 1fr); gap: 8px 14px; }
@media (max-width: 760px) { .rank { grid-template-columns: 1fr; } }

.item {
  display: flex;
  align-items: center;
  gap: 10px;
  background: var(--card);
  border-radius: 10px;
  box-shadow: var(--shadow);
  padding: 8px 12px 8px 8px;
  min-width: 0;
}
.item:hover { box-shadow: var(--shadow-hover); }

.no {
  flex: 0 0 auto;
  width: 22px;
  text-align: center;
  font-size: 13px;
  font-weight: 800;
  color: #c3b9ae;
  font-variant-numeric: tabular-nums;
}
.no.top1 { color: #e0451f; }
.no.top2 { color: #ef8b1f; }
.no.top3 { color: #c9a227; }

.thumb { flex: 0 0 auto; width: 40px; aspect-ratio: 3 / 4; border-radius: 6px; overflow: hidden; background: #eee; }
.thumb img { width: 100%; height: 100%; object-fit: cover; display: block; }

.info { flex: 1; min-width: 0; }
.name { font-size: 14px; font-weight: 700; display: block; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.name:hover { color: var(--primary); }
.meta { margin: 1px 0 0; font-size: 12px; color: var(--text-2); white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.latest { margin: 4px 0 0; font-size: 12px; color: var(--primary); white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }

.heat { flex: 0 0 auto; font-size: 12px; color: #b5aca2; font-variant-numeric: tabular-nums; }
</style>
