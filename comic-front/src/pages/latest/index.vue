<script setup lang="ts">
// 最近更新 —— 按 updatedAt 倒序列出源站刚同步过的漫画（后端 sort=updated）。
//
// **加载方式（2026-10-09 用户要求）**：触底**自动**追加，不再是上一页 / 下一页按钮。
// 触发用 uni 的页面级生命周期 `onReachBottom` —— 小程序没有 IntersectionObserver，
// 与 `pages/rank` 同一套做法（那边有详细说明）。
//
// **列表按本地日期分组**：组头「今天 / 昨天 / M月D日」+ 该组条数，组头**吸顶**在顶栏下方。
// ⚠️ 分组必须基于**已累积的全量**重算，不能每批各分一次 —— 每批 18 条时同一日期会被切在
//    两批之间（实测 09-20 / 09-21 两组都跨批），各分各的会出现重复的日期组头。
import { computed, onMounted, ref } from 'vue'
import { getComics } from '../../api'
import type { Comic } from '../../types'
import ComicCard from '../../components/ComicCard.vue'
import { onLoad, onReachBottom } from '@dcloudio/uni-app'
import { setRoute } from '../../utils/router'
import Layout from '../../components/Layout.vue'

// 每批条数。原来是「3 列 × 6 行 = 18，正好填满不留空」—— 分组后每组各是一个网格、
// 末行本来就可能不满，那条理由不再成立；18 保留下来只是作为「一批拉多少」的批次大小。
const PAGE_SIZE = 18

const comics = ref<Comic[]>([])
const total = ref(0)
const page = ref(1)
const loading = ref(false)
const ready = ref(false)   // 首屏是否已出结果（区分「首屏加载中」与「追加中」）
let reqId = 0              // 请求序号：并发 / 乱序时只认最后一次

/** 本地日期键（同一天归一组） */
function dayKey(iso: string): string {
  const d = new Date(iso)
  return `${d.getFullYear()}-${d.getMonth() + 1}-${d.getDate()}`
}

/** 日期标签：今天 / 昨天 / M月D日 */
function dayLabel(iso: string): string {
  const d = new Date(iso)
  d.setHours(0, 0, 0, 0)
  const today = new Date()
  today.setHours(0, 0, 0, 0)
  const days = Math.round((today.getTime() - d.getTime()) / 86400000)
  if (days === 0) return '今天'
  if (days === 1) return '昨天'
  return `${d.getMonth() + 1} 月 ${d.getDate()} 日`
}

interface DayGroup { key: string; label: string; items: Comic[] }

/**
 * 按日期分组（对已累积的全量重算，见文件头说明）。
 * 后端按 sync_time 倒序返回，所以组的出现顺序天然是从新到旧。
 */
const groups = computed<DayGroup[]>(() => {
  const out: DayGroup[] = []
  const index = new Map<string, DayGroup>()
  for (const c of comics.value) {
    const key = dayKey(c.updatedAt)
    let g = index.get(key)
    if (!g) {
      g = { key, label: dayLabel(c.updatedAt), items: [] }
      index.set(key, g)
      out.push(g)
    }
    g.items.push(c)
  }
  return out
})

const hasMore = computed(() => comics.value.length < total.value)

async function load(reset = false) {
  const id = ++reqId
  if (reset) {
    page.value = 1
    comics.value = []
    total.value = 0
  }
  loading.value = true
  try {
    const res = await getComics({ sort: 'updated', page: page.value, pageSize: PAGE_SIZE })
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

/** 触底 → 追加下一批（加载中不重入；已拉完不再请求） */
function loadMore() {
  if (loading.value || !hasMore.value) return
  page.value += 1
  void load()
}

onMounted(() => void load(true))
// uni 页面生命周期：登记该页对应的 web 路径（替代 vue-router 的路由状态）
onLoad((options) => setRoute('/latest', options ?? {}))
// 触底追加下一批（替代 IntersectionObserver）
onReachBottom(loadMore)
</script>

<template>
  <Layout>
    <view>
      <view class="section-title">最近更新</view>

      <view v-if="!ready" class="empty">加载中…</view>
      <view v-else-if="comics.length === 0" class="empty">暂无更新记录</view>

      <view v-else>
        <view v-for="g in groups" :key="g.key" class="day-group">
          <view class="day-head">
            <text class="day-label u-span">{{ g.label }}</text>
            <text class="day-count u-span">{{ g.items.length }} 部</text>
          </view>
          <view class="grid">
            <ComicCard v-for="c in g.items" :key="c.id" :comic="c" />
          </view>
        </view>

        <!-- 触底提示：自动加载，所以这里只是状态显示（不作点击热区） -->
        <view class="tail u-p">
          <text v-if="loading" class="u-span">加载中…</text>
          <text v-else-if="hasMore" class="u-span">继续下滑加载更多</text>
          <text v-else class="u-span">— 没有更多了 —</text>
        </view>
      </view>
    </view>
  </Layout>
</template>

<style scoped>
/* 日期组：组头吸顶在顶栏下方，滚过该组时被下一组顶走。
   ⚠️ top 取 60px = 顶栏 `.nav-inner` 的高度（`components/Layout.vue`，改那边要同步这里）；
   两者都改，否则组头会跟顶栏叠在一起。
   背景必须给实色（`var(--bg)` = 页面底色），否则下面的卡片会从组头底下透出来。 */
.day-head {
  position: sticky;
  top: 60px;
  z-index: 20;                 /* 盖住卡片；仍低于顶栏的 100 */
  display: flex;
  align-items: baseline;
  gap: 8px;
  padding: 10px 0 8px;
  background: var(--bg);
}
.day-label { font-size: 15px; font-weight: 800; color: var(--text); letter-spacing: 0.3px; }
.day-count { font-size: 12px; color: var(--text-2); }

/* 3 列网格（与首页 / 分类页一致）。列数不再跟批次大小挂钩 —— 分组后每组末行不满是正常的。 */
.grid { display: grid; grid-template-columns: repeat(3, 1fr); gap: 16px; }
/* 手机（≤560px）保持 3 列，只收紧间距（原先降到 2 列；2026-09-22 用户要求） */
@media (max-width: 560px) { .grid { gap: 10px; } }

/* 每组下留一段，免得两组贴在一起分不清边界 */
.day-group:not(:last-child) { margin-bottom: 10px; }

.tail { text-align: center; color: var(--text-2); font-size: 13px; margin: 22px 0 8px; }
</style>
