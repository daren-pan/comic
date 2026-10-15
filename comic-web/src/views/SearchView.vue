<script setup lang="ts">
import { computed, onMounted, ref, watch } from 'vue'
import {
  getCategories,
  getComics,
  importAndWait,
  searchSources,
  type ComicQuery,
  type ComicSort,
} from '../api'
import type { CategoryCount, SourceSearchGroup, SourceSearchItem } from '../types'
import ComicCard from '../components/ComicCard.vue'
import FilterBar from '../components/FilterBar.vue'
import { useRoute, useRouter } from 'vue-router'
import { usePagedList } from '../composables/usePagedList'
import { useScrollKeep } from '../composables/useScrollKeep'
import Layout from '../components/Layout.vue'
import Pager from '../components/Pager.vue'

const route = useRoute()
const router = useRouter()

const categories = ref<CategoryCount[]>([])
const category = ref('全部')
// 默认按热度降序（2026-09-22 用户要求）：进分类页先看「现在最热的」，而不是刚更新的
const sort = ref<ComicSort>('views')
const keyword = ref('')
const input = ref('')
/**
 * 列表状态机（分页 / 竞态 / 失败回退都在里面）—— 2026-10-13 抽自多页逐字重复的代码。
 * ⚠️ `immediate: false`：首屏由 `onMounted → applyQuery` 触发（要等分类读完）。
 */
const {
  items: comics, total, page, loading, error, totalPages, goPage, reload,
} = usePagedList(
  async (p, ps) => {
    // 每页条数 = 3 列 × 6 行 = 18 —— 正好填满，末行不留空格（2026-09-23 与「最近更新」页统一）。
    // ⚠️ 别再随手改成 20：20 ÷ 3 = 6 行余 2，末行就会空掉最后一格。
    const q: ComicQuery = {
      category: category.value === '全部' ? undefined : category.value,
      sort: sort.value,
      page: p,
      pageSize: ps,
    }
    if (keyword.value) q.keyword = keyword.value
    const res = await getComics(q)
    // 站内结果先渲染，再去源站找（源站慢，不能拖住站内结果的显示）
    if (keyword.value) void loadRemote(keyword.value)
    else resetRemote()
    return res
  },
  { pageSize: 18, immediate: false },
)

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

/** 来源显示名：页面不暴露源站实名（2026-10-12 用户要求）——
 *  copymanga → 线路一，zaimanhua → 线路二；其余来源暂无别名、原样显示。 */
const SOURCE_NAMES: Record<string, string> = { copymanga: '线路一', zaimanhua: '线路二' }
function sourceLabel(source: string): string {
  return SOURCE_NAMES[source] ?? source
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
  notice.value = `正在从 ${sourceLabel(item.source)} 导入《${item.title}》…`
  try {
    const r = await importAndWait({ source: item.source, sourceComicId: item.sourceComicId })
    // 跨源不合并：别的源收过同一部作品时，这里会作为独立的一部导入（译本/进度可能不同）
    notice.value = r.alreadySameSource
      ? `《${r.title}》已在 ${sourceLabel(r.source)} 收录过` +
        (r.newChapters ? `，本次补齐 ${r.newChapters} 话新章节` : '') + '（正在打开…）' 
      : `已导入《${r.title}》，共 ${r.chapters} 话，正在打开…`
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
  reload()
}

function onSearch() {
  keyword.value = input.value.trim()
  router.replace({ query: keyword.value ? { keyword: keyword.value } : {} })
  reload()
}

function onCategory(c: string) {
  category.value = c
  router.replace({ query: { ...route.query, category: c } })
  reload()
}

function onSort(s: ComicSort) {
  sort.value = s
  reload()
}

onMounted(async () => {
  categories.value = await getCategories()
  applyQuery()
})
// compat 层的 route.query 每次登记都会换成新对象；改看 fullPath（字符串按值比较）避免重复触发。
// ⚠️ keep-alive（2026-10-15）：本页被缓存后，fullPath 变化有两类「不该重搜」的情形 ——
//   ① 离开本页（进详情等）：路由已不是 search，不响应（否则后台会把列表重置掉）；
//   ② 从详情返回：URL 条件与当前列表一致，保留缓存结果（否则返回即重置回第 1 页）。
watch(() => route.fullPath, () => {
  if (route.name !== 'search') return // ① 已离开本页
  const c = route.query.category as string | undefined
  const k = route.query.keyword as string | undefined
  const nextCat = c && categories.value.some((x) => x.name === c) ? c : '全部'
  const nextKw = k ?? ''
  if (nextCat === category.value && nextKw === keyword.value) return // ② 条件未变 → 保留
  applyQuery()
})

// keep-alive：切走再回来停在原处（从详情返回时保留位置与页码，见 composables/useScrollKeep.ts）
useScrollKeep()
// uni 页面生命周期：登记该页对应的 web 路径（替代 vue-router 的路由状态）

</script>

<template>
  <Layout>
    <div>
      <div class="section-title">{{ keyword ? '搜索结果' : '分类浏览' }}</div>

      <div class="toolbar">
        <form class="big-search" @submit.prevent="onSearch">
          <input class="u-input" v-model="input" type="text" placeholder="输入漫画名 / 作者 / 标签…" />
          <button class="u-button" type="submit">搜索</button>
        </form>

        <FilterBar
          :category="category"
          :sort="sort"
          :categories="categories"
          @update:category="onCategory"
          @update:sort="onSort"
        />
      </div>

      <div v-if="keyword" class="result-hint u-p">
        关键词「{{ keyword }}」共 {{ total }} 部作品
      </div>

      <div v-if="error" class="empty">{{ error }}</div>
      <div v-else-if="loading" class="empty">搜索中…</div>
      <div v-else-if="comics.length === 0" class="empty">
        <template v-if="keyword">站内没有「{{ keyword }}」，看看下面的其他来源</template>
        <template v-else>没有找到相关漫画，换个关键词试试</template>
      </div>
      <div v-else class="grid">
        <ComicCard v-for="c in comics" :key="c.id" :comic="c" />
      </div>

      <Pager v-if="totalPages > 1" :page="page" :total-pages="totalPages" @change="goPage" />

      <!-- 其他来源：站内搜不到时去各源站找，点「导入并阅读」即可收录后打开 -->
      <template v-if="keyword">
        <div class="remote-title u-h3">
          其他来源
          <span v-if="remoteLoading" class="hint">正在搜索源站…</span>
        </div>

        <div v-if="notice" class="notice u-p">{{ notice }}</div>
        <div v-if="importError" class="notice err u-p">{{ importError }}</div>
        <div v-if="remoteError" class="empty u-p">{{ remoteError }}</div>
        <div v-else-if="!remoteLoading && remoteGroups.length === 0" class="empty u-p">
          其他来源也没有找到「{{ keyword }}」
        </div>

        <!-- 多个站点同时命中：用标签切换来源（结果是一次全拿到的，切换不重新请求） -->
        <div v-if="remoteGroups.length > 1" class="remote-tabs">
          <span class="tabs-label u-span">来源</span>
          <button
            v-for="g in remoteGroups"
            :key="g.source"
            class="remote-tab u-button"
            :class="{ on: activeSource === g.source }"
            @click="activeSource = g.source"
          >
            {{ sourceLabel(g.source) }}<span class="u-span">{{ g.items.length }}</span>
          </button>
        </div>

        <div v-if="activeGroup" class="remote-group">
          <!-- 只有一个来源时不显示标签条，改为一行来源说明 -->
          <div v-if="remoteGroups.length <= 1" class="remote-src">
            <span class="src-name u-span">{{ sourceLabel(activeGroup.source) }}</span>
            <span class="src-count u-span">{{ activeGroup.items.length }} 条</span>
          </div>
          <div class="remote-list">
            <div
              v-for="it in activeGroup.items"
              :key="it.source + it.sourceComicId"
              class="remote-item"
            >
              <img class="remote-cover u-img" :src="it.cover" :alt="it.title" loading="lazy" @error="hideImg"  />
              <div class="remote-info">
                <div class="remote-name">{{ it.title }}</div>
                <div class="remote-meta">
                  {{ it.author || '未知作者' }}
                  <span class="u-span" v-if="it.latestChapterTitle">· 更新至 {{ it.latestChapterTitle }}</span>
                </div>
                <div v-if="it.tags.length" class="remote-tags">
                  <span class="u-span" v-for="t in it.tags.slice(0, 4)" :key="t">{{ t }}</span>
                </div>
              </div>
              <div class="remote-action">
                <span v-if="it.comicId !== null" class="badge u-span">已收录</span>
                <button
                  class="btn u-button"
                  :disabled="!!importing"
                  @click="onImport(it)"
                >
                  {{
                    it.comicId !== null
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
  </Layout>
</template>

<style scoped>
.toolbar { display: flex; flex-direction: column; gap: 14px; margin-bottom: 18px; }

.big-search { display: flex; gap: 8px; }
.big-search .u-input {
  flex: 1;
  height: 44px;
  border: 2px solid var(--border);
  border-radius: 10px;
  padding: 0 16px;
  font-size: 15px;
  outline: none;
  transition: border 0.15s;
  background: var(--card);
}
.big-search .u-input:focus { border-color: var(--primary); }
.big-search .u-button {
  border: none;
  background: var(--primary);
  color: #fff;
  padding: 0 26px;
  border-radius: 10px;
  font-size: 15px;
  font-weight: 700;
  cursor: pointer;
}
.big-search .u-button:hover { background: var(--primary-dark); }

.result-hint { font-size: 13px; color: var(--text-2); margin: 0 0 12px; }

/* 3 列 × 6 行 = 18 = 每页条数 —— 正好填满，末行不留空格。
   ⚠️ 改列数时必须同步改 `pageSize`（两者相乘要等于每页条数），否则末行会空出来。
   网页版 6 列 × 3 行 = 18，同样整除（见文末 .mode-web 段）。 */
.grid { display: grid; grid-template-columns: repeat(3, 1fr); gap: 16px; }
/* 手机（≤560px）保持 3 列，只收紧间距（原先降到 2 列；2026-09-22 用户要求） */
@media (max-width: 560px) { .grid { gap: 10px; } }

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
  border: 1px solid var(--border); background: var(--card); color: var(--text-2);
  padding: 5px 14px; border-radius: 999px; font-size: 13px; cursor: pointer;
  transition: all 0.15s; display: inline-flex; align-items: center;
}
.remote-tab .u-span { color: #b5aca2; font-size: 12px; margin-left: 5px; }
.remote-tab:hover { border-color: var(--primary); color: var(--primary); }
.remote-tab.on { background: var(--primary); border-color: var(--primary); color: #fff; font-weight: 600; }
.remote-tab.on .u-span { color: rgba(255, 255, 255, 0.75); }

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
.remote-tags .u-span {
  font-size: 11px; padding: 1px 7px; border-radius: 6px;
  background: var(--primary-soft); color: var(--primary-dark);
}
.remote-action { display: flex; align-items: center; gap: 10px; flex: none; }
.remote-action .btn { padding: 6px 14px; font-size: 13px; }
.badge {
  font-size: 12px; padding: 2px 8px; border-radius: 6px;
  background: #eaf3de; color: #3b6d11;
}

/* 网页版（.mode-web，2026-10-10）：漫画网格 3 列 → 6 列（密度与首页一致；18 条 =
   6 列 × 3 行仍整除）；中窄宽窗降 4 列、超窄窗 3 列。 */
.mode-web .grid { grid-template-columns: repeat(6, 1fr); }
@media (max-width: 1024px) {
  .mode-web .grid { grid-template-columns: repeat(4, 1fr); }
}
@media (max-width: 560px) {
  .mode-web .grid { grid-template-columns: repeat(3, 1fr); }
}
</style>
