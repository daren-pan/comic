<script setup lang="ts">
// 热度排行 —— **一整条全库榜单**：按热度（后端 heat 字段）从高到低排，可切标签与排序口径。
// 热度口径：1000 起底 + 浏览次数×1 + 收藏数×2（见 crawler-service/mysql_storage.py）。
//
// 2026-09-22 改版（用户要求）：原先「每个标签单独一个区块」——30 个标签就是 30 个区块、
// 30 次请求，用户还得逐块看。现在改成**一条全库榜单 + 一条筛选条**（标签下拉 + 排序），
// 翻页沿用 `onReachBottom`（小程序没有 IntersectionObserver，见下）。
//
// ⚠️ 触发机制说明（2026-09-22 多端适配）：comic-web 用 `IntersectionObserver` 做「区块进视口才拉」，
// 但**小程序没有这个 API**（且 `uni.createIntersectionObserver` 只能按选择器观察，拿不到
// 函数式 ref 的元素）。改用 uni 的页面级生命周期 `onReachBottom` —— 三端一致、可用性等价
// （差别只是「滚到底」而非「进视口」触发）。
import { onMounted, ref } from 'vue'
import { getCategories, getComics, type ComicSort } from '../../api'
import type { CategoryCount, Comic } from '../../types'
import { onLoad, onReachBottom } from '@dcloudio/uni-app'
import { setRoute, useRouter } from '../../utils/router'
import Layout from '../../components/Layout.vue'
import FilterBar from '../../components/FilterBar.vue'

/** 每批拉取条数（= 一页），触底再拉下一批追加到榜尾 */
const PAGE_SIZE = 20

const router = useRouter()
const categories = ref<CategoryCount[]>([])
const category = ref('全部')
// 默认按热度降序（2026-09-22 用户要求）—— 排行榜的本分就是按热度排
const sort = ref<ComicSort>('views')
const comics = ref<Comic[]>([])
const total = ref(0)
const page = ref(1)
const loading = ref(false)
/** 首次加载是否已完成（用于区分「加载中」与「暂无数据」） */
const ready = ref(false)

// 竞态保护：切标签/排序会连发请求，只认最后一次的结果，避免旧响应盖掉新榜
let reqId = 0

async function load(reset = false) {
  const id = ++reqId
  if (reset) {
    page.value = 1
    comics.value = []
    total.value = 0
  }
  loading.value = true
  try {
    const res = await getComics({
      category: category.value === '全部' ? undefined : category.value,
      sort: sort.value,
      page: page.value,
      pageSize: PAGE_SIZE,
    })
    if (id !== reqId) return   // 已有更新的请求发出 → 丢弃本次结果
    comics.value = reset ? res.items : comics.value.concat(res.items)
    total.value = res.total
  } catch {
    if (id !== reqId) return
    if (reset) {
      comics.value = []
      total.value = 0
    } else {
      page.value = Math.max(1, page.value - 1)   // 追加失败 → 页码回退，下次触底重试
    }
  } finally {
    if (id === reqId) {
      loading.value = false
      ready.value = true
    }
  }
}

/** 触底 → 追加下一批 */
function loadMore() {
  if (loading.value || comics.value.length >= total.value) return
  page.value += 1
  load()
}

function onCategory(v: string) {
  if (v === category.value) return
  category.value = v
  load(true)
}

function onSort(s: ComicSort) {
  if (s === sort.value) return
  sort.value = s
  load(true)
}

function goSearch() {
  router.push({ path: '/search', query: category.value === '全部' ? {} : { category: category.value } })
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
  try {
    categories.value = await getCategories()
  } catch {
    categories.value = []
  }
  await load(true)
})

// uni 页面生命周期：登记该页对应的 web 路径（替代 vue-router 的路由状态）
onLoad((options) => setRoute('/rank', options ?? {}))
// 触底追加下一批（替代 IntersectionObserver）
onReachBottom(loadMore)

</script>

<template>
  <Layout>
    <view>
      <view class="head">
        <view class="section-title">🏆 热度排行</view>
        <view class="head-more u-a" @click="goSearch">在分类浏览中查看 ›</view>
      </view>
      <view class="lead u-p">
        全库按热度从高到低排序（热度 = 起底 1000 + 浏览 ×1 + 收藏 ×2，同分按最近更新）；
        可用标签筛选、切换排序口径。
      </view>

      <FilterBar
        :category="category"
        :sort="sort"
        :categories="categories"
        @update:category="onCategory"
        @update:sort="onSort"
      />

      <view v-if="!ready" class="empty">加载中…</view>
      <view v-else-if="comics.length === 0" class="empty">暂无排行数据</view>

      <template v-else>
        <view class="rank">
          <view v-for="(c, i) in comics" :key="c.id" class="item">
            <text class="no u-span" :class="rankClass(i)">{{ i + 1 }}</text>
            <view class="thumb u-a" @click="router.push(`/comic/${c.id}`)">
              <image mode="aspectFill" class="u-img" :src="c.cover" :alt="c.title" loading="lazy" />
            </view>
            <view class="info">
              <view class="name u-a" @click="router.push(`/comic/${c.id}`)">{{ c.title }}</view>
              <view class="meta u-p">{{ c.author }}</view>
              <view class="latest u-p">{{ c.latestChapterTitle || '暂无章节' }}</view>
            </view>
            <text class="heat u-span">🔥 {{ fmtHeat(c.heat) }}</text>
          </view>
        </view>

        <view class="more-hint u-p">
          <text v-if="loading">加载中…</text>
          <text v-else-if="comics.length >= total">已到底 · 共 {{ total }} 部</text>
          <text v-else>上滑加载更多（{{ comics.length }} / {{ total }}）</text>
        </view>
      </template>
    </view>
  </Layout>
</template>

<style scoped>
.head { display: flex; align-items: baseline; gap: 12px; }
.head-more { margin-left: auto; font-size: 12px; color: var(--primary); }
.head-more:hover { text-decoration: underline; }

.lead { color: var(--text-2); font-size: 14px; margin: -8px 0 16px; }

/* 单列榜单（本端只保留移动形态，2026-09-23；原桌面是 2 列）。
   PAGE_SIZE = 20 与列数无关（行式列表不分页填格），故无需同步改。 */
.rank { list-style: none; margin: 16px 0 0; padding: 0; display: grid; grid-template-columns: 1fr; gap: 8px 14px; }

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
  width: 26px;
  text-align: center;
  font-size: 13px;
  font-weight: 800;
  color: #c3b9ae;
  font-variant-numeric: tabular-nums;
}
.no.top1 { color: #e0451f; }
.no.top2 { color: #ef8b1f; }
.no.top3 { color: #c9a227; }

/* 缩略图：宽度固定 40px → 高度写死 54px（= 40 × 4/3）。不用 aspect-ratio，理由同 ComicCard。 */
.thumb { flex: 0 0 auto; width: 40px; height: 54px; border-radius: 6px; overflow: hidden; background: var(--bg); }
.thumb .u-img { width: 100%; height: 100%; object-fit: cover; display: block; }

.info { flex: 1; min-width: 0; }
.name { font-size: 14px; font-weight: 700; display: block; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; color: var(--text); text-decoration: none; }
.name:hover { color: var(--primary); }
.meta { margin: 1px 0 0; font-size: 12px; color: var(--text-2); white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.latest { margin: 4px 0 0; font-size: 12px; color: var(--primary); white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }

.heat { flex: 0 0 auto; font-size: 12px; color: #b5aca2; font-variant-numeric: tabular-nums; }

.more-hint { margin: 16px 0 4px; text-align: center; font-size: 13px; color: var(--text-2); }
</style>
