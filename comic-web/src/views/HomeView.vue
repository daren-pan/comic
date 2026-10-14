<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { getCategories, getComics } from '../api'
import type { CategoryCount, Comic } from '../types'
import ComicCard from '../components/ComicCard.vue'
import { useRouter } from 'vue-router'
import { getSeasonLogo } from '../utils/season'
import { useLayoutMode } from '../utils/layout'
import Layout from '../components/Layout.vue'

const router = useRouter()

// 站标随季节自动切换（春/夏/秋/冬 各一套图标 + 字标，见 utils/season.ts）
const logo = getSeasonLogo()

const categories = ref<CategoryCount[]>([])
const hotComics = ref<Comic[]>([])
const latestComics = ref<Comic[]>([])
const catComics = ref<Record<string, Comic[]>>({})
const loaded = ref(false)
/** 首屏取数失败的中文原因（空 = 无错）—— 修复前是裸 await：接口挂掉 `loaded` 永远为 false，页面卡「加载中…」 */
const loadError = ref('')

// 首页每个区块的展示条数：**移动端 3**（原样）、**网页版 6**（1180px 一行铺满，2026-10-10）。
// 取数统一按 6 条（多取 3 条成本可忽略），展示时按模式 slice —— 切换布局模式无需重新请求。
// 其余走标题右侧的「全部 ›」：分类块跳分类页按 category 查（分类页本来就支持 ?category= 直达），
// 热门 / 最新跳排行页、最近更新页。
const FETCH_N = 6
const { isWebMode } = useLayoutMode()
const shownN = computed(() => (isWebMode.value ? 6 : 3))
/** 区块展示列表：按当前模式截取（移动端 3 / 网页版 6）；列表未就绪时给空数组兜底 */
function shown(list?: Comic[]): Comic[] {
  return (list ?? []).slice(0, shownN.value)
}

// ---- 顶栏播报：图片轮播（PPT 式），轮番展示「最近更新」的前 6 部 ----
// 播报与「最新更新」区块**共用一次请求**（pageSize=6）：播报用全部 6 部，
// 区块按当前布局模式 slice（移动端 3 / 网页版 6，见 shown()）—— 省一次往返。
// 轮播自己写定时器（4s 一张、循环）；只在页面可见时自动播。
const MARQUEE_N = 6
const marquee = ref<Comic[]>([])
const pageVisible = ref(true)
const bcIndex = ref(0)
let bcTimer: ReturnType<typeof setInterval> | null = null

function startBc() {
  stopBc()
  bcTimer = setInterval(() => {
    if (marquee.value.length > 1) bcIndex.value = (bcIndex.value + 1) % marquee.value.length
  }, 4000)
}
function stopBc() {
  if (bcTimer) {
    clearInterval(bcTimer)
    bcTimer = null
  }
}
watch(marquee, (list) => {
  if (list.length > 1 && pageVisible.value) startBc()
})
watch(pageVisible, (v) => (v ? startBc() : stopBc()))

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

/**
 * 首屏取数（失败可重试；各区块数据为空时自然不渲染）。
 *
 * 分两路 catch 是刻意的：**分类读不到不拖垮首页**（它只是分类区块的入口），
 * 主数据（热门 / 最新 / 分类精选）失败才显示错误态 —— 修复前的裸 await 一旦
 * 任一步抛错，后面全不执行、`loaded` 永远 false，页面永久停在「加载中…」。
 */
async function loadHome() {
  loadError.value = ''
  loaded.value = false
  try {
    categories.value = await getCategories()
  } catch {
    categories.value = []
  }
  try {
    const cats = categories.value.filter((c) => c.name !== '全部').map((c) => c.name)

    const [hot, latest] = await Promise.all([
      getComics({ sort: 'views', pageSize: FETCH_N }),
      getComics({ sort: 'updated', pageSize: MARQUEE_N }),
    ])
    hotComics.value = hot.items
    marquee.value = latest.items
    latestComics.value = latest.items

    const picks = cats.slice(0, 4)
    const res = await Promise.all(picks.map((c) => getComics({ category: c, pageSize: FETCH_N })))
    picks.forEach((c, i) => (catComics.value[c] = res[i].items))
  } catch (e) {
    loadError.value = (e as Error).message || '加载失败'
  } finally {
    loaded.value = true
  }
}

onMounted(loadHome)
// 轮播只在可见时自动播：浏览器切到后台（visibilitychange）/ 离开页面（组件卸载）就暂停
function onVis() {
  pageVisible.value = document.visibilityState === 'visible'
}
onMounted(() => {
  pageVisible.value = true
  document.addEventListener('visibilitychange', onVis)
})
onBeforeUnmount(() => {
  pageVisible.value = false
  stopBc()
  document.removeEventListener('visibilitychange', onVis)
})

</script>

<template>
  <Layout>
    <div>
      <!-- 顶栏（2026-10-07 用户要求换掉原来的「聚合全网好漫画」hero）：
           ① 站标：logo + 名称（名称暂定「聚漫画」）
           ② 播报：图片轮播（PPT 式切换），轮番展示「最近更新」的前 5 部，点一张进它的详情页
           （2026-10-07 全站改名：漫阅 → 聚漫画） -->
      <div class="top-bar">
        <div class="brand">
          <img class="brand-icon" :src="logo.icon"  />
          <img class="brand-text" :src="logo.text"  />
        </div>
        <div class="broadcast">
          <div class="bc-swiper">
            <div class="bc-track" :style="{ transform: `translateX(-${bcIndex * 100}%)` }">
              <div v-for="c in marquee" :key="c.id" class="bc-slide-wrap" @click="goComic(c)">
                <div class="bc-slide">
                  <!-- 同图模糊铺底（竖版封面放进横条不留白）+ 完整封面居中 -->
                  <img class="bc-bg" :src="c.cover" />
                  <img class="bc-fg" :src="c.cover" :alt="c.title" />
                  <div class="bc-caption">
                    <span class="bc-title u-span">《{{ c.title }}》</span>
                    <span class="bc-sub u-span">更新至 {{ c.latestChapterTitle || '最新话' }}</span>
                  </div>
                </div>
              </div>
            </div>
            <div v-if="marquee.length > 1" class="bc-dots">
              <span v-for="(c, i) in marquee" :key="c.id" class="bc-dot" :class="{ on: i === bcIndex }"></span>
            </div>
          </div>
        </div>
      </div>

      <!-- 热门榜：只放前三，其余走「全部 ›」→ 排行页 -->
      <div class="section-title">
        <span class="st-label">热门榜单</span>
        <div class="more u-a" @click="goAll('/rank')">全部 ›</div>
      </div>
      <div class="grid">
        <ComicCard v-for="c in shown(hotComics)" :key="c.id" :comic="c" />
      </div>

      <!-- 最新更新：同样只放前三，「全部 ›」→ 最近更新页 -->
      <div class="section-title">
        <span class="st-label">最新更新</span>
        <span class="hint">（源站同步 · {{ fmtTime(latestComics[0]?.updatedAt ?? Date.now().toString()) }}内有更新）</span>
        <div class="more u-a" @click="goAll('/latest')">全部 ›</div>
      </div>
      <div class="grid">
        <ComicCard v-for="c in shown(latestComics)" :key="c.id" :comic="c" />
      </div>

      <!-- 分类浏览：每块只放前 3 部，标题右侧「全部」跳分类页查该标签下的所有漫画 -->
      <template v-for="cat in categories.filter((x) => x.name !== '全部').slice(0, 4)" :key="cat.name">
        <div class="section-title">
          <span class="st-label">{{ cat.name }} · 精选</span>
          <div class="more u-a" @click="goCategory(cat.name)">全部 ›</div>
        </div>
        <div class="grid">
          <ComicCard v-for="c in shown(catComics[cat.name])" :key="c.id" :comic="c" />
        </div>
      </template>

      <div v-if="loadError" class="empty u-p">
        {{ loadError }}
        <span class="retry u-a" @click="loadHome">重试</span>
      </div>
      <div v-else-if="!loaded" class="empty">加载中…</div>
    </div>
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
.bc-swiper { position: relative; height: 260px; overflow: hidden; }
/* 轮播轨道：横向排布 N 张，靠 translateX 切换（transition 与 uni swiper 的 500ms 对齐） */
.bc-track { display: flex; height: 100%; transition: transform 0.5s ease; }
.bc-slide-wrap { flex: 0 0 100%; height: 100%; cursor: pointer; }
/* 指示点（替代 uni swiper 的 indicator-dots） */
.bc-dots { position: absolute; left: 0; right: 0; bottom: 10px; display: flex; justify-content: center; gap: 6px; pointer-events: none; }
.bc-dot { width: 6px; height: 6px; border-radius: 50%; background: rgba(255, 255, 255, 0.5); }
.bc-dot.on { background: #fff; }
.bc-slide { position: relative; width: 100%; height: 100%; overflow: hidden; }
/* 同图模糊铺底：竖版封面放进横条时两侧不留白。
   ① 用 top/left/right/bottom 而不是 `inset`（兼容面更稳）；
   ② 放大一点，盖住模糊在边缘的透明衰减。 */
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

/* 区块标题文字：flex 项默认可被压缩换行 —— 窄屏实测会把「最新更新」挤成「最新更 / 新」两行，
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

/* ==================== 网页版（.mode-web，2026-10-10） ==================== */
/* 品牌行：网页版站标已在顶部导航条里，藏掉页面内重复的那份；轮播升成整宽 hero */
.mode-web .brand { display: none; }
.mode-web .bc-swiper { height: 300px; }
/* 区块网格 3 列 → 6 列（展示条数同步 3 → 6，见脚本 shown()）；中窄宽窗降回 4 列 */
.mode-web .grid { grid-template-columns: repeat(6, 1fr); }
@media (max-width: 1024px) {
  .mode-web .grid { grid-template-columns: repeat(4, 1fr); }
}
/* 超窄窗（≤560px，手机上强开网页版）：密度收回 3 列 */
@media (max-width: 560px) {
  .mode-web .grid { grid-template-columns: repeat(3, 1fr); }
}

/* 首屏错误态的重试入口（2026-10-13 补错误处理时加） */
.retry { margin-left: 8px; color: var(--primary); font-weight: 700; text-decoration: underline; cursor: pointer; }
</style>
