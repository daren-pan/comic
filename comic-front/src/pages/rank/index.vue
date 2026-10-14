<script setup lang="ts">
// 热度排行 —— **一整条全库榜单**：按热度（后端 heat 字段）从高到低排，可切标签与排序口径。
// 热度口径：1000 起底 + 浏览次数×1 + 收藏数×2（见 crawler-service/mysql_storage.py）。
//
// 2026-09-22 改版（用户要求）：原先「每个标签单独一个区块」——30 个标签就是 30 个区块、
// 30 次请求，用户还得逐块看。现在改成**一条全库榜单 + 一条筛选条**（标签下拉 + 排序），
// 翻页沿用 `onReachBottom`（见下）。
//
// ⚠️ 触发机制说明（2026-09-22）：comic-web 用 `IntersectionObserver` 做「区块进视口才拉」，
// 这里改用 uni 的页面级生命周期 `onReachBottom` —— 可用性等价
// （差别只是「滚到底」而非「进视口」触发）。
import { onMounted, ref } from 'vue'
import { getCategories, getComics, type ComicSort } from '../../api'
import type { CategoryCount, Comic } from '../../types'
import { onLoad, onReachBottom } from '@dcloudio/uni-app'
import { setRoute, useRouter } from '../../utils/router'
import { usePagedList } from '../../composables/usePagedList'
import { formatHeat } from '../../utils/format'
import Layout from '../../components/Layout.vue'
import FilterBar from '../../components/FilterBar.vue'

/** 每批拉取条数（= 一页），触底再拉下一批追加到榜尾 */
const PAGE_SIZE = 20

const router = useRouter()
const categories = ref<CategoryCount[]>([])
const category = ref('全部')
// 默认按热度降序（2026-09-22 用户要求）—— 排行榜的本分就是按热度排
const sort = ref<ComicSort>('views')
// 列表状态机全部收在 composable 里（竞态保护 / 触底追加 / 追加失败页码回退 / `ready` 语义）——
// 此前这段与 `pages/latest` **一字不差**，见 `composables/usePagedList.ts` 的文件头。
const { items: comics, total, loading, ready, loadMore, reload } = usePagedList<Comic>(
  (page, pageSize) =>
    getComics({
      category: category.value === '全部' ? undefined : category.value,
      sort: sort.value,
      page,
      pageSize,
    }),
  { pageSize: PAGE_SIZE },
)

function onCategory(v: string) {
  if (v === category.value) return
  category.value = v
  reload()
}

function onSort(s: ComicSort) {
  if (s === sort.value) return
  sort.value = s
  reload()
}

function goSearch() {
  router.push({ path: '/search', query: category.value === '全部' ? {} : { category: category.value } })
}

function rankClass(i: number): string {
  return i === 0 ? 'top1' : i === 1 ? 'top2' : i === 2 ? 'top3' : ''
}

// 热度格式化已收进 `utils/format.ts` 的 `formatHeat`（2026-10-13）

onMounted(async () => {
  try {
    categories.value = await getCategories()
  } catch {
    categories.value = []
  }
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
        <view class="section-title">热度排行</view>
        <view class="head-more u-a" @click="goSearch">在分类浏览中查看 ›</view>
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
            <text class="heat u-span">🔥 {{ formatHeat(c.heat) }}</text>
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
