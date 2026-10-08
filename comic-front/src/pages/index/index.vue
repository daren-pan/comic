<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { getCategories, getComics } from '../../api'
import type { CategoryCount, Comic } from '../../types'
import ComicCard from '../../components/ComicCard.vue'
import { onHide, onLoad, onShow, onUnload } from '@dcloudio/uni-app'
import { setRoute, useRouter } from '../../utils/router'
import { getSeasonLogo } from '../../utils/season'
import Layout from '../../components/Layout.vue'

const router = useRouter()

// 站标随季节自动切换（春/夏/秋/冬 各一套图标 + 字标，见 utils/season.ts）
const logo = getSeasonLogo()

const categories = ref<CategoryCount[]>([])
const hotComics = ref<Comic[]>([])
const latestComics = ref<Comic[]>([])
const catComics = ref<Record<string, Comic[]>>({})
const loaded = ref(false)

// 首页每个区块只放「排名最前的三部」（热门榜单 / 最新更新 / 分类精选 一律如此）——
// 其余走标题右侧的「全部 ›」：分类块跳分类页按 category 查（分类页本来就支持 ?category= 直达），
// 热门 / 最新跳排行页、最近更新页。
const TOP_N = 3

// ---- 顶栏播报：图片轮播（PPT 式），轮番展示「最近更新」的前 5 部 ----
// 为什么单独取 5 条：下面「最新更新」区块只要 3 部（TOP_N），而播报要 5 部 ——
// 一次请求 pageSize=5，区块再 slice(0, TOP_N)，省一次往返。
// 轮播本身交给 uni 的 <swiper autoplay>（不用自己写定时器）；只在页面可见时自动播。
const MARQUEE_N = 5
const marquee = ref<Comic[]>([])
const pageVisible = ref(true)

/** 点播报里那条 → 进它的详情页（与卡片同一套路由） */
function goComic(c?: Comic) {
  if (c) router.push(`/comic/${c.id}`)
}

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
    getComics({ sort: 'updated', pageSize: MARQUEE_N }),
  ])
  hotComics.value = hot.items
  marquee.value = latest.items
  latestComics.value = latest.items.slice(0, TOP_N)

  const picks = cats.slice(0, 4)
  const res = await Promise.all(picks.map((c) => getComics({ category: c, pageSize: TOP_N })))
  picks.forEach((c, i) => (catComics.value[c] = res[i].items))
  loaded.value = true
})
// uni 页面生命周期：登记该页对应的 web 路径（替代 vue-router 的路由状态）
onLoad((options) => setRoute('/', options ?? {}))
// 轮播只在可见时自动播：切 Tab（onHide）/ 离开（onUnload）就暂停
onShow(() => (pageVisible.value = true))
onHide(() => (pageVisible.value = false))
onUnload(() => (pageVisible.value = false))

</script>

<template>
  <Layout>
    <view>
      <!-- 顶栏（2026-10-07 用户要求换掉原来的「聚合全网好漫画」hero）：
           ① 站标：logo + 名称（名称暂定「聚漫画」）
           ② 播报：图片轮播（PPT 式切换），轮番展示「最近更新」的前 5 部，点一张进它的详情页
           （2026-10-07 全站改名：漫阅 → 聚漫画） -->
      <view class="top-bar">
        <view class="brand">
          <image class="brand-icon" :src="logo.icon" mode="aspectFit" />
          <image class="brand-text" :src="logo.text" mode="aspectFit" />
        </view>
        <view class="broadcast">
          <swiper
            class="bc-swiper"
            :autoplay="pageVisible"
            :interval="4000"
            :duration="500"
            :circular="true"
            :indicator-dots="true"
            indicator-color="rgba(255, 255, 255, 0.5)"
            indicator-active-color="#ffffff"
          >
            <swiper-item v-for="c in marquee" :key="c.id" @click="goComic(c)">
              <view class="bc-slide">
                <!-- 同图模糊铺底（竖版封面放进横条不留白）+ 完整封面居中（aspectFit 不裁切） -->
                <image class="bc-bg" mode="aspectFill" :src="c.cover" />
                <image class="bc-fg" mode="aspectFit" :src="c.cover" :alt="c.title" />
                <view class="bc-caption">
                  <text class="bc-title u-span">《{{ c.title }}》</text>
                  <text class="bc-sub u-span">更新至 {{ c.latestChapterTitle || '最新话' }}</text>
                </view>
              </view>
            </swiper-item>
          </swiper>
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
/* ---- 顶栏：站标 + 图片轮播（播报）----
   ① 站标 = 图片（图标 + 字标），随季节自动切换，资源见 static/logo/ 与 utils/season.ts。
      图片已去白底（字标）与四角白边（图标），浅色 / 夜间两种主题下都能用。
   ② 轮播用 uni 内置 `<swiper autoplay>`（PPT 式逐张切换）—— 不用自己写定时器；
      自动播由 `pageVisible` 控制（切到别的 Tab 就暂停）。 */
.top-bar {
  display: flex;
  flex-direction: column;
  gap: 10px;
  margin-bottom: 14px;
}
.brand { display: flex; align-items: center; gap: 8px; }
.brand-icon { width: 30px; height: 30px; }
/* 字标是 2:1 横排图，图上下各留白约 20% —— 高度 34px 时字面高约 20px */
.brand-text { width: 68px; height: 34px; }

.broadcast { border-radius: 14px; overflow: hidden; background: var(--surface-2); }
.bc-swiper { height: 260px; }
.bc-slide { position: relative; width: 100%; height: 100%; overflow: hidden; }
/* 同图模糊铺底：竖版封面放进横条时两侧不留白。
   ① 用 top/left/right/bottom 而不是 `inset`（小程序端 CSS 支持面更稳）；
   ② 放大一点，盖住模糊在边缘的透明衰减；
   ③ `filter: blur()` 在 H5 正常；小程序端若不支持，退化成"未模糊的铺底图"（仍能看，不报错）。 */
.bc-bg {
  position: absolute;
  top: 0;
  left: 0;
  right: 0;
  bottom: 0;
  width: 100%;
  height: 100%;
  filter: blur(20px) brightness(0.55);
  transform: scale(1.15);
}
/* 完整封面居中：aspectFit 不裁切（这是 B 方案与"横幅裁切"的区别） */
.bc-fg { position: relative; width: 100%; height: 100%; }
/* 文案压在图底：加一层渐变保证任何封面上都读得清 */
.bc-caption {
  position: absolute;
  left: 0;
  right: 0;
  bottom: 0;
  padding: 22px 14px 10px;
  background: linear-gradient(to top, rgba(0, 0, 0, 0.72), rgba(0, 0, 0, 0));
  color: #fff;
}
.bc-title { font-size: 15px; font-weight: 700; }
.bc-sub { font-size: 12px; color: rgba(255, 255, 255, 0.86); margin-left: 6px; }

.grid {
  display: grid;
  grid-template-columns: repeat(3, 1fr);
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

/* 手机（≤560px）**保持 3 列**（2026-09-22 用户要求「移动端每行三部、增加信息量」，
   原先这里降到 2 列）；只收紧间距 —— 每列约 110px，间距从 16 收到 10 能让封面宽一点。
   卡片自身的字号/内边距由 ComicCard.vue 里的同名断点负责。
   ⚠️ 本端只保留移动形态（2026-09-23），故**没有**桌面列数、也没有 900px 那档断点。 */
@media (max-width: 560px) {
  .grid { gap: 10px; }
  /* 窄屏轮播矮一档：竖版封面在 390px 宽下按高度自适应，太高会占掉整屏 */
  .bc-swiper { height: 210px; }
  /* 标题行容不下「最新更新」+ 长提示 + 「全部 ›」→ 提示让位，只留标题与链接（实测 390px 会换行） */
  .section-title .hint { display: none; }
}
</style>
