<script setup lang="ts">
import { onMounted, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { getCategories, getComics, type ComicQuery, type ComicSort } from '../api'
import type { CategoryCount, Comic } from '../types'
import ComicCard from '../components/ComicCard.vue'

const route = useRoute()
const router = useRouter()

const categories = ref<CategoryCount[]>([])
const category = ref('全部')
const sort = ref<ComicSort>('updated')
const keyword = ref('')
const input = ref('')
const comics = ref<Comic[]>([])
const total = ref(0)
const page = ref(1)
const pageSize = 12
const loading = ref(false)

async function load() {
  loading.value = true
  const q: ComicQuery = { category: category.value === '全部' ? undefined : category.value, sort: sort.value, page: page.value, pageSize }
  if (keyword.value) q.keyword = keyword.value
  const res = await getComics(q)
  comics.value = res.items
  total.value = res.total
  loading.value = false
}

function applyQuery() {
  // 从 URL 恢复过滤条件（支持首页分类入口直达）
  const c = route.query.category as string | undefined
  const k = route.query.keyword as string | undefined
  category.value = c && categories.value.some((x) => x.name === c) ? c : '全部'
  keyword.value = k ?? ''
  input.value = k ?? ''
  page.value = 1
  load()
}

function onSearch() {
  keyword.value = input.value.trim()
  router.replace({ query: keyword.value ? { keyword: keyword.value } : {} })
  page.value = 1
  load()
}

function onCategory(c: string) {
  category.value = c
  router.replace({ query: { ...route.query, category: c } })
  page.value = 1
  load()
}

function onSort(s: ComicSort) {
  sort.value = s
  page.value = 1
  load()
}

const totalPages = () => Math.max(1, Math.ceil(total.value / pageSize))

onMounted(async () => {
  categories.value = await getCategories()
  applyQuery()
})
watch(() => route.query, applyQuery)
</script>

<template>
  <div>
    <h2 class="section-title">{{ keyword ? '搜索结果' : '分类浏览' }}</h2>

    <div class="toolbar">
      <form class="big-search" @submit.prevent="onSearch">
        <input v-model="input" type="text" placeholder="输入漫画名 / 作者 / 标签…" />
        <button type="submit">搜索</button>
      </form>

      <div class="cats">
        <button
          v-for="c in categories"
          :key="c.name"
          class="chip-btn"
          :class="{ on: category === c.name }"
          @click="onCategory(c.name)"
        >{{ c.name }}<span>{{ c.count }}</span></button>
      </div>

      <div class="sorts">
        <span class="label">排序</span>
        <button :class="{ on: sort === 'updated' }" @click="onSort('updated')">最新更新</button>
        <button :class="{ on: sort === 'views' }" @click="onSort('views')">最热</button>
      </div>
    </div>

    <p v-if="keyword" class="result-hint">
      关键词「{{ keyword }}」共 {{ total }} 部作品
    </p>

    <div v-if="loading" class="empty">搜索中…</div>
    <div v-else-if="comics.length === 0" class="empty">没有找到相关漫画，换个关键词试试</div>
    <div v-else class="grid">
      <ComicCard v-for="c in comics" :key="c.id" :comic="c" />
    </div>

    <div v-if="totalPages() > 1" class="pager">
      <button class="btn ghost" :disabled="page <= 1" @click="page--; load()">上一页</button>
      <span class="page-info">{{ page }} / {{ totalPages() }}</span>
      <button class="btn ghost" :disabled="page >= totalPages()" @click="page++; load()">下一页</button>
    </div>
  </div>
</template>

<style scoped>
.toolbar { display: flex; flex-direction: column; gap: 14px; margin-bottom: 18px; }

.big-search { display: flex; gap: 8px; }
.big-search input {
  flex: 1;
  height: 44px;
  border: 2px solid var(--border);
  border-radius: 10px;
  padding: 0 16px;
  font-size: 15px;
  outline: none;
  transition: border 0.15s;
  background: #fff;
}
.big-search input:focus { border-color: var(--primary); }
.big-search button {
  border: none;
  background: var(--primary);
  color: #fff;
  padding: 0 26px;
  border-radius: 10px;
  font-size: 15px;
  font-weight: 700;
  cursor: pointer;
}
.big-search button:hover { background: var(--primary-dark); }

.cats { display: flex; gap: 8px; flex-wrap: wrap; }
.chip-btn {
  border: 1px solid var(--border);
  background: #fff;
  padding: 5px 14px;
  border-radius: 999px;
  font-size: 13px;
  cursor: pointer;
  transition: all 0.15s;
  color: var(--text);
}
.chip-btn span { color: #b5aca2; font-size: 12px; margin-left: 3px; }
.chip-btn:hover { border-color: var(--primary); color: var(--primary); }
.chip-btn.on { background: var(--primary); border-color: var(--primary); color: #fff; }
.chip-btn.on span { color: rgba(255, 255, 255, 0.75); }

.sorts { display: flex; align-items: center; gap: 8px; }
.sorts .label { font-size: 13px; color: var(--text-2); }
.sorts button {
  border: 1px solid var(--border);
  background: #fff;
  padding: 4px 12px;
  border-radius: 8px;
  font-size: 13px;
  cursor: pointer;
  color: var(--text-2);
}
.sorts button.on { background: var(--primary-soft); color: var(--primary); border-color: var(--primary); font-weight: 600; }

.result-hint { font-size: 13px; color: var(--text-2); margin: 0 0 12px; }

.grid { display: grid; grid-template-columns: repeat(5, 1fr); gap: 16px; }
@media (max-width: 900px) { .grid { grid-template-columns: repeat(3, 1fr); } }
@media (max-width: 560px) { .grid { grid-template-columns: repeat(2, 1fr); } }

.pager { display: flex; align-items: center; justify-content: center; gap: 16px; margin-top: 26px; }
.page-info { color: var(--text-2); font-size: 14px; }
</style>
