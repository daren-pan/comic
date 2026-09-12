<script setup lang="ts">
import { computed, onMounted, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import {
  getCategories,
  getComics,
  importAndWait,
  searchSources,
  type ComicQuery,
  type ComicSort,
} from '../api'
import type { CategoryCount, Comic, SourceSearchGroup, SourceSearchItem } from '../types'
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

// ---- 其他来源（源站搜索）：站内搜不到时去各源站找 ----
const remoteGroups = ref<SourceSearchGroup[]>([])
const activeSource = ref('')    // 当前查看哪个源的结果（多源时用标签切换）
const remoteLoading = ref(false)
const remoteError = ref('')     // 源站搜索本身的问题（如全部失败）
const importing = ref('')       // 正在导入的条目 key（source:sourceComicId）
const notice = ref('')          // 导入进度 / 结果提示
const importError = ref('')     // 导入失败原因（如该作品在源站取不到图）

/** 多源时只渲染当前选中的那一组；结果是一次全拿到的，切换标签不重新请求 */
const activeGroup = computed(
  () => remoteGroups.value.find((g) => g.source === activeSource.value) ?? remoteGroups.value[0] ?? null,
)

async function load() {
  loading.value = true
  const q: ComicQuery = { category: category.value === '全部' ? undefined : category.value, sort: sort.value, page: page.value, pageSize }
  if (keyword.value) q.keyword = keyword.value
  const res = await getComics(q)
  comics.value = res.items
  total.value = res.total
  loading.value = false
  // 站内结果先渲染，再去源站找（源站慢，不能拖住站内结果的显示）
  if (keyword.value) void loadRemote(keyword.value)
  else resetRemote()
}

function resetRemote() {
  remoteGroups.value = []
  activeSource.value = ''
  remoteError.value = ''
  importError.value = ''
  notice.value = ''
}

/** 搜源站（只读、不写库）；结果回来时若关键词已变则丢弃，避免竞态串台 */
async function loadRemote(kw: string) {
  resetRemote()
  remoteLoading.value = true
  try {
    const groups = await searchSources(kw)
    if (kw === keyword.value) {
      remoteGroups.value = groups
      activeSource.value = groups[0]?.source ?? ''   // 默认看主源（服务端按 SOURCES 顺序返回）
    }
  } catch (e) {
    if (kw === keyword.value) remoteError.value = (e as Error).message || '其他来源暂时不可用'
  } finally {
    if (kw === keyword.value) remoteLoading.value = false
  }
}

/** 「导入并阅读」：未收录 → 导入后跳详情；已收录 → 直接跳详情 */
async function onImport(item: SourceSearchItem) {
  if (item.comicId) {
    router.push(`/comic/${item.comicId}`)
    return
  }
  if (importing.value) return
  importing.value = `${item.source}:${item.sourceComicId}`
  importError.value = ''
  notice.value = `正在从 ${item.source} 导入《${item.title}》…`
  try {
    const r = await importAndWait({ source: item.source, sourceComicId: item.sourceComicId })
    notice.value = `已导入《${r.title}》，共 ${r.chapters} 话，正在打开…`
    router.push(`/comic/${r.comicId}`)
  } catch (e) {
    notice.value = ''
    importError.value = (e as Error).message || '导入失败'
  } finally {
    importing.value = ''
  }
}

/** 源站封面是外链（可能被防盗链拦）：加载失败就隐藏，不留破图 */
function hideImg(e: Event) {
  const el = e.target as HTMLImageElement | null
  if (el) el.style.visibility = 'hidden'
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
    <div v-else-if="comics.length === 0" class="empty">
      <template v-if="keyword">站内没有「{{ keyword }}」，看看下面的其他来源</template>
      <template v-else>没有找到相关漫画，换个关键词试试</template>
    </div>
    <div v-else class="grid">
      <ComicCard v-for="c in comics" :key="c.id" :comic="c" />
    </div>

    <div v-if="totalPages() > 1" class="pager">
      <button class="btn ghost" :disabled="page <= 1" @click="page--; load()">上一页</button>
      <span class="page-info">{{ page }} / {{ totalPages() }}</span>
      <button class="btn ghost" :disabled="page >= totalPages()" @click="page++; load()">下一页</button>
    </div>

    <!-- 其他来源：站内搜不到时去各源站找，点「导入并阅读」即可收录后打开 -->
    <template v-if="keyword">
      <h3 class="remote-title">
        其他来源
        <small v-if="remoteLoading" class="hint">正在搜索源站…</small>
      </h3>

      <p v-if="notice" class="notice">{{ notice }}</p>
      <p v-if="importError" class="notice err">{{ importError }}</p>
      <p v-if="remoteError" class="empty">{{ remoteError }}</p>
      <p v-else-if="!remoteLoading && remoteGroups.length === 0" class="empty">
        其他来源也没有找到「{{ keyword }}」
      </p>

      <!-- 多个站点同时命中：用标签切换来源（结果是一次全拿到的，切换不重新请求） -->
      <div v-if="remoteGroups.length > 1" class="remote-tabs">
        <span class="tabs-label">来源</span>
        <button
          v-for="g in remoteGroups"
          :key="g.source"
          class="remote-tab"
          :class="{ on: activeSource === g.source }"
          @click="activeSource = g.source"
        >
          {{ g.source }}<span>{{ g.items.length }}</span>
        </button>
      </div>

      <div v-if="activeGroup" class="remote-group">
        <!-- 只有一个来源时不显示标签条，改为一行来源说明 -->
        <div v-if="remoteGroups.length <= 1" class="remote-src">
          <span class="src-name">{{ activeGroup.source }}</span>
          <span class="src-count">{{ activeGroup.items.length }} 条</span>
        </div>
        <div class="remote-list">
          <div
            v-for="it in activeGroup.items"
            :key="it.source + it.sourceComicId"
            class="remote-item"
          >
            <img class="remote-cover" :src="it.cover" :alt="it.title" loading="lazy" @error="hideImg" />
            <div class="remote-info">
              <div class="remote-name">{{ it.title }}</div>
              <div class="remote-meta">
                {{ it.author || '未知作者' }}
                <span v-if="it.latestChapterTitle">· 更新至 {{ it.latestChapterTitle }}</span>
              </div>
              <div v-if="it.tags.length" class="remote-tags">
                <span v-for="t in it.tags.slice(0, 4)" :key="t">{{ t }}</span>
              </div>
            </div>
            <div class="remote-action">
              <span v-if="it.inLibrary" class="badge">已收录</span>
              <button
                class="btn"
                :disabled="!!importing"
                @click="onImport(it)"
              >
                {{
                  it.inLibrary
                    ? '打开'
                    : importing === it.source + ':' + it.sourceComicId
                      ? '导入中…'
                      : '导入并阅读'
                }}
              </button>
            </div>
          </div>
        </div>
      </div>
    </template>
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

/* ---- 其他来源（源站搜索 + 按需导入） ---- */
.remote-title { margin: 34px 0 14px; font-size: 18px; display: flex; align-items: baseline; gap: 10px; }
.remote-title .hint { font-size: 13px; font-weight: 400; color: var(--text-2); }

.notice {
  margin: 0 0 12px; padding: 9px 14px; border-radius: 10px;
  background: var(--primary-soft); color: var(--primary-dark); font-size: 13px;
}
.notice.err { background: #fdeceb; color: #a32d2d; }

.remote-group { margin-bottom: 18px; }
/* 多站点命中时的来源切换标签 */
.remote-tabs { display: flex; align-items: center; gap: 8px; margin-bottom: 12px; flex-wrap: wrap; }
.remote-tabs .tabs-label { font-size: 13px; color: var(--text-2); }
.remote-tab {
  border: 1px solid var(--border); background: #fff; color: var(--text-2);
  padding: 5px 14px; border-radius: 999px; font-size: 13px; cursor: pointer;
  transition: all 0.15s; display: inline-flex; align-items: center;
}
.remote-tab span { color: #b5aca2; font-size: 12px; margin-left: 5px; }
.remote-tab:hover { border-color: var(--primary); color: var(--primary); }
.remote-tab.on { background: var(--primary); border-color: var(--primary); color: #fff; font-weight: 600; }
.remote-tab.on span { color: rgba(255, 255, 255, 0.75); }

.remote-src { display: flex; align-items: center; gap: 8px; margin-bottom: 8px; font-size: 14px; }
.remote-src .src-name { font-weight: 600; }
.remote-src .src-count { font-size: 12px; color: var(--text-2); }

.remote-list { display: flex; flex-direction: column; gap: 8px; }
.remote-item {
  display: flex; align-items: center; gap: 14px;
  padding: 10px 14px; background: var(--card);
  border: 1px solid var(--border); border-radius: var(--radius);
}
.remote-cover {
  width: 44px; height: 60px; flex: none;
  object-fit: cover; border-radius: 6px; background: var(--bg);
}
.remote-info { flex: 1; min-width: 0; }
.remote-name {
  font-size: 14px; font-weight: 600; color: var(--text);
  overflow: hidden; text-overflow: ellipsis; white-space: nowrap;
}
.remote-meta { font-size: 12px; color: var(--text-2); margin-top: 3px; }
.remote-tags { display: flex; gap: 6px; margin-top: 5px; flex-wrap: wrap; }
.remote-tags span {
  font-size: 11px; padding: 1px 7px; border-radius: 6px;
  background: var(--primary-soft); color: var(--primary-dark);
}
.remote-action { display: flex; align-items: center; gap: 10px; flex: none; }
.remote-action .btn { padding: 6px 14px; font-size: 13px; }
.badge {
  font-size: 12px; padding: 2px 8px; border-radius: 6px;
  background: #eaf3de; color: #3b6d11;
}
</style>
