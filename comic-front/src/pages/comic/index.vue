<script setup lang="ts">
import { computed, ref } from 'vue'
import { onLoad } from '@dcloudio/uni-app'
import { getChapter, getChapters, getComic, getHistoryWithDetail, isFavorite, toggleFavorite, upsertHistory } from '../../api'
import { useUserStore } from '../../stores/user'
import { openNewTab, setRoute, useRoute, useRouter } from '../../utils/router'
import Layout from '../../components/Layout.vue'
import type { Chapter, Comic, HistoryEntry } from '../../types'

const route = useRoute()
const router = useRouter()
// 路由参数改由 uni 的 onLoad(options) 提供（uni 页面栈没有 vue-router 的 params）
let comicId = 0
const { isLoggedIn } = useUserStore()

const comic = ref<Comic>()
const chapters = ref<Chapter[]>([])
const fav = ref(false)
const loading = ref(true)
const favNotice = ref(false)
// 「续读」：本书在「最近阅读」里的那条记录 —— 数据源与「我的书架 · 最近阅读」同一个接口；
// null = 没读过 → 主按钮显示「▶ 开始阅读」
const lastRead = ref<(HistoryEntry & { chapterTitle?: string }) | null>(null)

const chapterCount = computed(() => chapters.value.length)

// 章节列表按 orderNo（源站 chapter_order）倒序：最新章节在前，符合阅读习惯。
// 仅在此视图内反向，不改后端接口、不影响阅读器「上一话/下一话」方向。
const sortedChapters = computed(() =>
  [...chapters.value].sort((a, b) => b.orderNo - a.orderNo),
)

async function load() {
  const [c, chs, f, his] = await Promise.all([
    getComic(comicId),
    getChapters(comicId),
    isLoggedIn ? isFavorite(comicId) : Promise.resolve(false),
    getHistoryWithDetail(),
  ])
  comic.value = c
  chapters.value = chs
  fav.value = f
  // 同一部作品在历史里只会有一条（历史表按 (user_id, comic_id) 唯一）
  lastRead.value = his.find((h) => h.comicId === comicId) ?? null
  loading.value = false
}

// uni 页面生命周期：取路由参数 → 登记 web 路径 → 加载数据
onLoad((options) => {
  comicId = Number(options?.id ?? 0)
  setRoute(`/comic/${comicId}`, options ?? {})
  void load()
})

async function onFav() {
  // 收藏需要登录；未登录引导去登录页
  if (!isLoggedIn) {
    favNotice.value = true
    return
  }
  favNotice.value = false
  fav.value = await toggleFavorite(comicId)
}

function gotoLogin() {
  router.push({ path: '/login', query: { redirect: route.fullPath } })
}

/** 新标签页打开阅读器：详情页保留在当前标签页（H5 开新标签，其他端退化为同页跳转） */
function openReader(chapterId: number) {
  openNewTab(`/reader/${comicId}/${chapterId}`)
}

async function read(chapter: Chapter) {
  await upsertHistory({ comicId, chapterId: chapter.id, pageNo: 1 })
  openReader(chapter.id)
}

/**
 * 主按钮：读过 → **续读**（新标签页打开上次那一话，与书架「续读」完全一致，
 * 且**不重置进度** —— 只有点章节列表才会把进度写回第 1 页）；
 * 没读过 → 「开始阅读」，打开最新章节。
 */
function onPrimaryRead() {
  if (lastRead.value) {
    openReader(lastRead.value.chapterId)
    return
  }
  if (sortedChapters.value.length) void read(sortedChapters.value[0])
}

function fmtTime(iso: string): string {
  const d = new Date(iso)
  return `${d.getMonth() + 1}月${d.getDate()}日`
}
</script>

<template>
  <Layout>
    <view v-if="loading" class="empty">加载中…</view>
    <view v-else-if="comic" class="detail">
      <view class="hero">
        <image mode="aspectFill" class="hero-cover u-img" :src="comic.cover" :alt="comic.title" />
        <view class="hero-info">
          <view class="u-h1">{{ comic.title }}</view>
          <view class="hero-meta u-p">
            <text class="chip u-span">{{ comic.category }}</text>
            <text class="chip done u-span" v-if="comic.status === '已完结'">{{ comic.status }}</text>
            <text class="chip hot u-span" v-else>{{ comic.status }}</text>
            <text class="tag u-span" v-for="t in comic.tags" :key="t">#{{ t }}</text>
          </view>
          <view class="hero-line u-p">作者：{{ comic.author }}</view>
          <view class="hero-line u-p">章节：{{ chapterCount }} 话 · 热度 {{ comic.heat.toLocaleString() }} · 更新 {{ fmtTime(comic.updatedAt) }}</view>
          <view class="hero-line sources u-p">数据来源：<text class="u-em">{{ comic.source }}</text></view>
          <view class="actions">
            <button class="btn u-button" @click="onPrimaryRead">
              {{ lastRead ? `续读${lastRead.chapterTitle ?? ''}` : '▶ 开始阅读' }}
            </button>
            <button class="btn ghost u-button" :class="{ active: fav }" @click="onFav">
              {{ fav ? '★ 已收藏' : '☆ 收藏' }}
            </button>
          </view>
          <view v-if="favNotice" class="fav-notice u-p">
            收藏需要登录 — <view class="u-a" @click="gotoLogin">去登录</view>，登录后可跨设备同步收藏
          </view>
        </view>
      </view>

      <view class="desc u-p">{{ comic.description }}</view>

      <view class="section-title">章节列表（{{ chapterCount }}）</view>
      <view class="chapters">
        <button
          v-for="(ch, i) in sortedChapters"
          :key="ch.id"
          class="chapter u-button"
          @click="read(ch)"
        >
          <text class="no u-span">{{ i + 1 }}</text>
          <text class="name u-span">{{ ch.title }}</text>
        </button>
      </view>
    </view>
  </Layout>
</template>

<style scoped>
.hero {
  display: flex;
  gap: 24px;
  background: #fff;
  border-radius: 16px;
  padding: 22px;
  box-shadow: var(--shadow);
}
.hero-cover { width: 190px; height: 253px; border-radius: 10px; object-fit: cover; flex-shrink: 0; box-shadow: 0 6px 18px rgba(0,0,0,0.18); }
.hero-info { flex: 1; min-width: 0; }
.hero-info .u-h1 { margin: 0 0 10px; font-size: 26px; }
.hero-meta { display: flex; align-items: center; gap: 8px; flex-wrap: wrap; margin: 0 0 12px; }
.chip.done { background: #eef0f2; color: #555; }
.chip.hot { background: #fff3e6; color: #b25f00; }
.tag { font-size: 12px; color: var(--text-2); }
.hero-line { margin: 4px 0; color: var(--text-2); font-size: 14px; }
.sources .u-em {
  font-style: normal;
  background: #f0ede8;
  border-radius: 6px;
  padding: 1px 8px;
  font-size: 12px;
  margin-right: 6px;
  color: var(--text-2);
}
.actions { display: flex; gap: 10px; margin-top: 16px; }
.fav-notice {
  margin-top: 10px;
  font-size: 13px;
  color: var(--primary-dark);
  background: var(--primary-soft);
  border-radius: 8px;
  padding: 8px 12px;
}
.fav-notice .u-a { color: var(--primary); font-weight: 700; text-decoration: underline; }

.desc {
  background: #fff;
  border-radius: 12px;
  padding: 14px 18px;
  margin: 16px 0 0;
  color: var(--text-2);
  font-size: 14px;
  line-height: 1.8;
  border-left: 4px solid var(--primary);
}

.chapters {
  display: grid;
  grid-template-columns: repeat(3, 1fr);
  gap: 10px;
}
.chapter {
  display: flex;
  align-items: center;
  gap: 10px;
  background: #fff;
  border: 1px solid var(--border);
  border-radius: 10px;
  padding: 10px 14px;
  cursor: pointer;
  transition: all 0.15s;
  text-align: left;
  font-size: 14px;
}
.chapter:hover { border-color: var(--primary); background: var(--primary-soft); transform: translateY(-1px); }
.no {
  width: 22px; height: 22px;
  border-radius: 6px;
  background: var(--primary-soft);
  color: var(--primary);
  font-weight: 700;
  font-size: 12px;
  display: flex; align-items: center; justify-content: center;
  flex-shrink: 0;
}
.name { flex: 1; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; font-weight: 600; color: var(--text); }

@media (max-width: 700px) {
  .hero { flex-direction: column; align-items: center; text-align: center; }
  .hero-meta, .actions { justify-content: center; }
  .chapters { grid-template-columns: 1fr; }
}
</style>
