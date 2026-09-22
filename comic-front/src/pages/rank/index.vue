<script setup lang="ts">
// 热度排行 —— 按分类分区块，各分类内按热度（后端 heat 字段）倒序取前 N 部。
// 热度口径：1000 起底 + 浏览次数×1 + 收藏数×2（见 crawler-service/mysql_storage.py）。
//
// 分类很多（库内 70+ 个标签），为避免一次性发出几十个请求，这里做**分批懒加载**：
// 首屏只渲染/请求前 BATCH 个分类，用户**滚动到底部**再追加一批。
//
// ⚠️ 触发机制说明（2026-09-22 多端适配）：comic-web 用 `IntersectionObserver` 做「区块进视口才拉」，
// 但**小程序没有这个 API**（且 `uni.createIntersectionObserver` 只能按选择器观察，拿不到
// 函数式 ref 的元素）。改用 uni 的页面级生命周期 `onReachBottom` —— 三端一致、可用性等价
// （差别只是「滚到底」而非「进视口」触发，请求次数与首屏开销都不变）。
import { computed, onMounted, ref } from 'vue'
import { getCategories, getComics } from '../../api'
import type { CategoryCount, Comic } from '../../types'
import { onLoad, onReachBottom } from '@dcloudio/uni-app'
import { setRoute, useRouter } from '../../utils/router'
import Layout from '../../components/Layout.vue'

/** 每个分类榜单展示的作品数 */
const TOP_N = 10
/** 少于该作品数的分类不单独设榜（1~2 部排不出名次） */
const MIN_COUNT = 3
/** 首批渲染的分类数，也是每次触底追加的数量 */
const BATCH = 4

const router = useRouter()
const cats = ref<CategoryCount[]>([])
const lists = ref<Record<string, Comic[]>>({})
const pending = ref<Record<string, boolean>>({})
const ready = ref(false)
/** 已渲染的分类数（懒加载水位线：触底就 +BATCH） */
const visibleCount = ref(BATCH)

/** 当前实际渲染的分类区块 */
const catsToShow = computed(() => cats.value.slice(0, visibleCount.value))

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

/** 把「已渲染但还没拉过」的分类补齐（首屏与每次触底追加后都走它） */
function ensureLoaded() {
  for (const cat of catsToShow.value) loadCategory(cat.name)
}

/** 触底 → 追加一批分类 */
function loadMore() {
  if (visibleCount.value >= cats.value.length) return
  visibleCount.value += BATCH
  ensureLoaded()
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
    const all = await getCategories()
    cats.value = all
      .filter((c) => c.name !== '全部' && c.count >= MIN_COUNT)
      .sort((a, b) => b.count - a.count)
  } catch {
    cats.value = []
  } finally {
    ready.value = true
    // 首批：分类数据到位后立刻拉；其余等触底
    ensureLoaded()
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
      <view class="section-title">🏆 热度排行</view>
      <view class="lead u-p">
        按分类分区块，每个分类内按热度从高到低取前 {{ TOP_N }} 部（热度 = 起底 1000 + 浏览 ×1 + 收藏 ×2，同分按最近更新）；
        仅收录作品数 ≥ {{ MIN_COUNT }} 的分类，作品多的分类排在前面。
      </view>

      <view v-if="!ready" class="empty">加载中…</view>
      <view v-else-if="cats.length === 0" class="empty">暂无排行数据</view>

      <template v-else>
        <view
          v-for="cat in catsToShow"
          :key="cat.name"
          class="block"
        >
          <view class="block-head u-h3">
            <text class="block-name u-span">{{ cat.name }}</text>
            <text class="block-count u-span">{{ cat.count }} 部</text>
            <view class="block-more u-a" @click="router.push({ path: '/search', query: { category: cat.name } })">查看全部 ›</view>
          </view>

          <view v-if="!lists[cat.name]" class="block-loading">加载中…</view>
          <view v-else class="rank">
            <view v-for="(c, i) in lists[cat.name]" :key="c.id" class="item">
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
        </view>
      </template>
    </view>
  </Layout>
</template>

<style scoped>
.lead { color: var(--text-2); font-size: 14px; margin: -8px 0 18px; }

.block { margin-bottom: 26px; }
.block-head { display: flex; align-items: baseline; gap: 8px; margin: 0 0 10px; font-size: 16px; }
.block-name { font-weight: 800; }
.block-count { font-size: 12px; color: var(--text-2); font-weight: 500; }
.block-more { margin-left: auto; font-size: 12px; color: var(--primary); text-decoration: none; }
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

/* 缩略图：宽度固定 40px → 高度写死 54px（= 40 × 4/3）。不用 aspect-ratio，理由同 ComicCard。 */
.thumb { flex: 0 0 auto; width: 40px; height: 54px; border-radius: 6px; overflow: hidden; background: var(--bg); }
.thumb .u-img { width: 100%; height: 100%; object-fit: cover; display: block; }

.info { flex: 1; min-width: 0; }
.name { font-size: 14px; font-weight: 700; display: block; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; color: var(--text); text-decoration: none; }
.name:hover { color: var(--primary); }
.meta { margin: 1px 0 0; font-size: 12px; color: var(--text-2); white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.latest { margin: 4px 0 0; font-size: 12px; color: var(--primary); white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }

.heat { flex: 0 0 auto; font-size: 12px; color: #b5aca2; font-variant-numeric: tabular-nums; }
</style>
