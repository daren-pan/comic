<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { getCategories, getComics } from '../../api'
import type { CategoryCount, Comic } from '../../types'
import ComicCard from '../../components/ComicCard.vue'
import { onLoad } from '@dcloudio/uni-app'
import { setRoute, useRouter } from '../../utils/router'
import Layout from '../../components/Layout.vue'

const router = useRouter()

const categories = ref<CategoryCount[]>([])
const hotComics = ref<Comic[]>([])
const latestComics = ref<Comic[]>([])
const catComics = ref<Record<string, Comic[]>>({})
const loaded = ref(false)

// 首页每个区块只放「排名最前的三部」（热门榜单 / 最新更新 / 分类精选 一律如此）——
// 其余走标题右侧的「全部 ›」：分类块跳分类页按 category 查（分类页本来就支持 ?category= 直达），
// 热门 / 最新跳排行页、最近更新页。
const TOP_N = 3

// 点标题右侧「全部」：带上该分类跳分类页（分类页 applyQuery 会读 URL 里的 category）
function goCategory(name: string) {
  router.push({ path: '/search', query: { category: name } })
}

// 热门 / 最新的「全部 ›」：各自跳对应的整页列表
function goAll(path: string) {
  router.push(path)
}

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
    getComics({ sort: 'views', pageSize: TOP_N }),
    getComics({ sort: 'updated', pageSize: TOP_N }),
  ])
  hotComics.value = hot.items
  latestComics.value = latest.items

  const picks = cats.slice(0, 4)
  const res = await Promise.all(picks.map((c) => getComics({ category: c, pageSize: TOP_N })))
  picks.forEach((c, i) => (catComics.value[c] = res[i].items))
  loaded.value = true
})
// uni 页面生命周期：登记该页对应的 web 路径（替代 vue-router 的路由状态）
onLoad((options) => setRoute('/', options ?? {}))

</script>

<template>
  <Layout>
    <view>
      <!-- Banner -->
      <view class="banner">
        <view class="banner-inner">
          <view class="u-h1">聚合全网好漫画<view class="u-br" /><text class="u-em">一个书架，全网追更</text></view>
          <view class="u-p">多源采集 · 分源收录 · 秒级同步更新 —— 源站一更新，这里几分钟可见</view>
          <view class="banner-badges">
            <text class="u-span" v-for="c in categories.filter((x) => x.name !== '全部').slice(0, 6)" :key="c.name">
              {{ c.name }} {{ c.count }}
            </text>
          </view>
        </view>
      </view>

      <!-- 热门榜：只放前三，其余走「全部 ›」→ 排行页 -->
      <view class="section-title">
        <text class="st-label">🔥 热门榜单</text>
        <view class="more u-a" @click="goAll('/rank')">全部 ›</view>
      </view>
      <view class="grid">
        <ComicCard v-for="c in hotComics" :key="c.id" :comic="c" />
      </view>

      <!-- 最新更新：同样只放前三，「全部 ›」→ 最近更新页 -->
      <view class="section-title">
        <text class="st-label">⚡ 最新更新</text>
        <text class="hint">（源站同步 · {{ fmtTime(latestComics[0]?.updatedAt ?? Date.now().toString()) }}内有更新）</text>
        <view class="more u-a" @click="goAll('/latest')">全部 ›</view>
      </view>
      <view class="grid">
        <ComicCard v-for="c in latestComics" :key="c.id" :comic="c" />
      </view>

      <!-- 分类浏览：每块只放前 3 部，标题右侧「全部」跳分类页查该标签下的所有漫画 -->
      <template v-for="cat in categories.filter((x) => x.name !== '全部').slice(0, 4)" :key="cat.name">
        <view class="section-title">
          <text class="st-label">{{ cat.name }} · 精选</text>
          <view class="more u-a" @click="goCategory(cat.name)">全部 ›</view>
        </view>
        <view class="grid">
          <ComicCard v-for="c in catComics[cat.name]" :key="c.id" :comic="c" />
        </view>
      </template>

      <view v-if="!loaded" class="empty">加载中…</view>
    </view>
  </Layout>
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
.banner .u-h1 { font-size: 30px; margin: 0 0 10px; line-height: 1.35; }
.banner .u-h1 .u-em { font-style: normal; color: var(--accent); }
.banner .u-p { margin: 0 0 16px; color: #e8dcd2; font-size: 14px; }
.banner-badges { display: flex; gap: 8px; flex-wrap: wrap; }
.banner-badges .u-span {
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
.hint {
  font-size: 12px;
  font-weight: 500;
  color: var(--text-2);
  margin-left: 4px;
  flex: 0 1 auto;
  min-width: 0;
  white-space: nowrap;
  overflow: hidden;
}

/* 区块标题文字：flex 项默认可被压缩换行 —— 窄屏实测会把「⚡ 最新更新」挤成「最新更 / 新」两行，
   这里锁死不折行；空间不够时让同行的 .hint 先让位（窄屏直接隐藏，见下方媒体查询）。 */
.st-label { flex: 0 0 auto; white-space: nowrap; }

/* 「全部 ›」：贴区块标题右侧（.section-title 本身是 flex，靠 margin-left:auto 顶到最右） */
.more {
  margin-left: auto;
  font-size: 13px;
  font-weight: 600;
  color: var(--primary);
  white-space: nowrap;
}
.more:hover { color: var(--primary-dark); text-decoration: underline; }

@media (max-width: 900px) {
  .grid { grid-template-columns: repeat(3, 1fr); }
}
/* 手机（≤560px）**保持 3 列**（2026-09-22 用户要求「移动端每行三部、增加信息量」，
   原先这里降到 2 列）；只收紧间距 —— 每列约 110px，间距从 16 收到 10 能让封面宽一点。
   卡片自身的字号/内边距由 ComicCard.vue 里的同名断点负责。 */
@media (max-width: 560px) {
  .grid { gap: 10px; }
  .banner .u-h1 { font-size: 24px; }
  /* 标题行容不下「最新更新」+ 长提示 + 「全部 ›」→ 提示让位，只留标题与链接（实测 390px 会换行） */
  .section-title .hint { display: none; }
}
</style>
