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

/**
 * 点标签 / 作者 → 搜索页按该条件筛。
 *
 * 走 `keyword` 而不是 `category`：后端 `list_comics` 的 keyword 同时匹配
 * **标题 / 作者 / 分类 / 标签名**（`t.name LIKE`），所以标签和作者都能直达；
 * 而 `category` 是"精确等于某个标签名"，且搜索页 `applyQuery` 会拿分类下拉的选项校验，
 * 非顶层分类的标签会被丢掉 —— 所以统一用 keyword 最稳。
 */
function goSearch(kw: string) {
  const k = String(kw || '').trim()
  if (k) router.push({ path: '/search', query: { keyword: k } })
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
            <!-- ⚠️ 这里**不再**放 `comic.category` 那个 chip：它是"魔法, 校园"这种原始串，
                 与下面的 tags 是同一批信息（tags 就是从它拆出来的），并排显示会重复。
                 现在**每个标签一个 chip**、都可点 → 搜索页按该标签筛。 -->
            <text class="chip done u-span" v-if="comic.status === '已完结'">{{ comic.status }}</text>
            <text class="chip hot u-span" v-else>{{ comic.status }}</text>
            <text
              class="tag u-span"
              v-for="t in comic.tags"
              :key="t"
              :title="`搜索「${t}」`"
              @click="goSearch(t)"
            >{{ t }}</text>
          </view>
          <view class="hero-line u-p">
            作者：<text
              class="u-a author-link"
              :title="`搜索作者「${comic.author}」`"
              @click="goSearch(comic.author)"
            >{{ comic.author }}</text>
          </view>
          <!-- 2026-10-07 用户要求：这行去掉「章节：N 话」与「热度 X」，只留更新时间
               （章节数在下面「章节列表（N）」里本来就有，不必在 hero 重复） -->
          <view class="hero-line u-p">更新 {{ fmtTime(comic.updatedAt) }}</view>
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
/* ⚠️ 本端只保留移动形态（2026-09-23）：原桌面态（封面 190×253 + 大标题 + 24px 间距）
   已删除，原 `@media (max-width: 700px)` 的移动规则**提升为基础态**，断点整体移除。
   卡片仍是**横向**的（封面左上、明细右上），只是整体缩小 —— 不是上下堆叠：
   堆叠会把封面下的空间全浪费掉，横向布局一屏能多露出半屏章节。 */
.hero {
  display: flex;
  align-items: flex-start;
  gap: 12px;
  background: var(--card);
  border-radius: 16px;
  padding: 14px;
  box-shadow: var(--shadow);
}
.hero-cover { width: 96px; height: 128px; border-radius: 8px; object-fit: cover; flex-shrink: 0; box-shadow: 0 6px 18px rgba(0,0,0,0.18); }
.hero-info { flex: 1; min-width: 0; }
.hero-info .u-h1 { margin: 0 0 6px; font-size: 17px; }
.hero-meta { display: flex; align-items: center; gap: 6px; flex-wrap: wrap; margin: 0 0 6px; }
/* 作者名是链接（点了进搜索页）：只加**下划线**做可点提示（2026-10-07 用户明确要求：
   不要改主题色/加粗/箭头，下划线就够）；颜色随正文，指针仍是手型。 */
.author-link {
  text-decoration: underline;
  cursor: pointer;
}
/* 状态徽标：底色与文字都取主题变量 —— 写死浅底会在夜间变成「浅底 + 浅字」 */
.chip.done { background: var(--mute); color: var(--text-2); }
.chip.hot { background: var(--primary-soft); color: var(--primary-dark); }
.tag {
  font-size: 12px;
  color: var(--text-2);
  padding: 1px 8px;
  border: 1px solid var(--border);
  border-radius: 999px;
  background: var(--card);
  cursor: pointer;
}
.tag:hover { color: var(--primary-dark); border-color: var(--primary); }
.hero-line { margin: 2px 0; color: var(--text-2); font-size: 12px; }
.sources .u-em {
  font-style: normal;
  background: var(--mute);
  border-radius: 6px;
  padding: 1px 8px;
  font-size: 12px;
  margin-right: 6px;
  color: var(--text-2);
}
.actions { display: flex; gap: 8px; margin-top: 10px; flex-wrap: wrap; }
.actions .btn { padding: 7px 12px; font-size: 13px; }
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
  background: var(--card);
  border-radius: 12px;
  padding: 10px 12px;
  margin: 12px 0 0;
  color: var(--text-2);
  font-size: 13px;
  line-height: 1.7;
  border-left: 4px solid var(--primary);
}

/* 章节：每行 4 个。列宽只剩 ~80px，序号徽标要占掉一半宽度 → 隐藏，只留标题
   （标题本身就是「第 12 话」这样的短语），居中排布。 */
.chapters {
  display: grid;
  grid-template-columns: repeat(4, 1fr);
  gap: 8px;
}
.chapter {
  display: flex;
  align-items: center;
  justify-content: center;
  background: var(--card);
  border: 1px solid var(--border);
  border-radius: 10px;
  padding: 9px 4px;
  cursor: pointer;
  transition: all 0.15s;
  text-align: center;
  font-size: 12px;
  gap: 0;
}
.chapter:hover { border-color: var(--primary); background: var(--primary-soft); transform: translateY(-1px); }
.chapter .no { display: none; }
.name { flex: 1 1 auto; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; font-weight: 600; color: var(--text); text-align: center; }
</style>
