<script setup lang="ts">
import { computed, ref } from 'vue'
import { onLoad } from '@dcloudio/uni-app'
import { addComment, deleteComment, getChapter, getChapters, getComic, getComments, getHistoryWithDetail, isFavorite, toggleFavorite, upsertHistory } from '../../api'
import { useUserStore } from '../../stores/user'
import { openNewTab, setRoute, useRoute, useRouter } from '../../utils/router'
import { storage } from '../../utils/storage'
import Layout from '../../components/Layout.vue'
import type { Chapter, Comic, Comment, HistoryEntry } from '../../types'

const route = useRoute()
const router = useRouter()
// 路由参数改由 uni 的 onLoad(options) 提供（uni 页面栈没有 vue-router 的 params）
let comicId = 0
const { isLoggedIn, isAdmin } = useUserStore()

const comic = ref<Comic>()
const chapters = ref<Chapter[]>([])
const fav = ref(false)
const loading = ref(true)
const favNotice = ref(false)
/** 作品不存在或**已下架**（详情接口 404）→ 整页显示一句人话，而不是干等「加载中…」 */
const gone = ref(false)
// 「续读」：本书在「最近阅读」里的那条记录 —— 数据源与「我的书架 · 最近阅读」同一个接口；
// null = 没读过 → 主按钮显示「▶ 开始阅读」
const lastRead = ref<(HistoryEntry & { chapterTitle?: string }) | null>(null)

const chapterCount = computed(() => chapters.value.length)

/** 章节排序方向：'desc' = 最新在前（默认），'asc' = 从第 1 话开始 */
type ChapterOrder = 'desc' | 'asc'

/** 排序偏好的存储键（走项目统一的 storage 适配层，与主题的 `comic_theme` 同一套路） */
const ORDER_KEY = 'comic_chapter_order'

/** 排序偏好：**默认倒序**（与改造前行为一致）；切过就记住，重进详情页仍是上次选的方向 */
const chapterOrder = ref<ChapterOrder>(storage.get(ORDER_KEY) === 'asc' ? 'asc' : 'desc')

const ORDERS: { value: ChapterOrder; label: string }[] = [
  { value: 'desc', label: '倒序' },
  { value: 'asc', label: '正序' },
]

function setOrder(v: ChapterOrder) {
  chapterOrder.value = v
  storage.set(ORDER_KEY, v)
}

// 章节列表按 orderNo（源站 chapter_order）排序，方向由 chapterOrder 决定。
// 仅在此视图内排序，不改后端接口、不影响阅读器「上一话/下一话」方向。
const sortedChapters = computed(() =>
  [...chapters.value].sort((a, b) =>
    chapterOrder.value === 'desc' ? b.orderNo - a.orderNo : a.orderNo - b.orderNo,
  ),
)

async function load() {
  loading.value = true
  try {
    comic.value = await getComic(comicId)
  } catch {
    // ⚠️ 详情接口 404 有两种原因：**作品已下架**（口径见后端 services/catalog）或 id 不存在。
    // 后端**故意**让两者返回同一个 404（不暴露"存在但被下架"），所以前端也不区分，统一给一句人话。
    gone.value = true
    loading.value = false
    return
  }
  // 其余几路**各自兜底**：任一路失败都不该把整页卡在「加载中…」。
  // 此前这里是裸的 `Promise.all` —— 一个 401（token 过期时的收藏接口）就让 loading 永远为 true，
  // 页面白屏只有「加载中…」，实测踩过（见 .workbuddy/memory 2026-10-09）。
  const [chs, f, his] = await Promise.all([
    getChapters(comicId).catch(() => [] as Chapter[]),
    isLoggedIn ? isFavorite(comicId).catch(() => false) : Promise.resolve(false),
    getHistoryWithDetail().catch(() => [] as HistoryEntry[]),
  ])
  chapters.value = chs
  fav.value = f
  // 同一部作品在历史里只会有一条（历史表按 (user_id, comic_id) 唯一）
  lastRead.value = his.find((h) => h.comicId === comicId) ?? null
  loading.value = false
  void loadComments()
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

// ---------------- 评论区 ----------------
//
// 三件事分得很开（别混）：
// - **列表**任何人可看；`enabled=false` 时接口照样 200，只是列表空 —— 所以关闭态要
//   自己显示「评论区已关闭」，不能靠"空列表"猜；
// - **发表**要登录（未登录按钮换成「登录后可评论」）；后端还会再判一次开关（403）；
// - **删除**是管理动作，只有管理员看得到按钮（真门在后端 `require_admin`）。

const comments = ref<Comment[]>([])
const commentTotal = ref(0)
const commentEnabled = ref(true)
const commentDraft = ref('')
const commentLoading = ref(false)
const commentSending = ref(false)
const commentNotice = ref('')     // 发表失败时的中文提示（后端文案直出）

/** 还有下一页吗（列表是"加载更多"式追加，不是分页器） */
const hasMoreComments = computed(() => comments.value.length < commentTotal.value)

/** 评论时间：今天只给时分，其余给「M月D日」（与分组列表的粒度一致） */
function fmtCommentTime(iso: string): string {
  const d = new Date(iso)
  const today = new Date()
  const sameDay =
    d.getFullYear() === today.getFullYear() &&
    d.getMonth() === today.getMonth() &&
    d.getDate() === today.getDate()
  const pad = (n: number) => String(n).padStart(2, '0')
  return sameDay ? `${pad(d.getHours())}:${pad(d.getMinutes())}` : `${d.getMonth() + 1}月${d.getDate()}日`
}

/** 拉评论（`append=false` 重载第一页；失败不打断整页 —— 评论区是"页脚"，不该把人挡在外面） */
async function loadComments(append = false) {
  if (commentLoading.value) return
  commentLoading.value = true
  try {
    const page = append ? Math.floor(comments.value.length / 20) + 1 : 1
    const res = await getComments(comicId, page)
    comments.value = append ? comments.value.concat(res.items) : res.items
    commentTotal.value = res.total
    commentEnabled.value = res.enabled
  } catch {
    if (!append) {
      comments.value = []
      commentTotal.value = 0
    }
  } finally {
    commentLoading.value = false
  }
}

async function sendComment() {
  const content = commentDraft.value.trim()
  if (!content || commentSending.value) return
  commentSending.value = true
  commentNotice.value = ''
  try {
    await addComment(comicId, content)
    commentDraft.value = ''
    // 重拉第一页而不是本地插入：作者名等字段的兜底规则只有后端一份（见 serializers.to_comment）
    await loadComments()
  } catch (e) {
    commentNotice.value = e instanceof Error ? e.message : '发表失败'
  } finally {
    commentSending.value = false
  }
}

async function removeComment(id: number) {
  commentNotice.value = ''
  try {
    await deleteComment(id)
    await loadComments()
  } catch (e) {
    commentNotice.value = e instanceof Error ? e.message : '删除失败'
  }
}

function gotoLoginForComment() {
  router.push({ path: '/login', query: { redirect: route.fullPath } })
}
</script>

<template>
  <Layout>
    <view v-if="loading" class="empty">加载中…</view>
    <view v-else-if="gone" class="empty">
      <view>作品不存在或已下架</view>
      <button class="btn ghost u-button back-home" @click="router.push('/')">回首页</button>
    </view>
    <view v-else-if="comic" class="detail">
      <!-- 左栏（作品卡 + 简介）包一层：移动端它是**无样式包裹层**（渲染与不加完全一致），
           网页版靠它把「封面 + 简介」作为一个整体做 sticky 左栏（见文末 .mode-web 段）。 -->
      <view class="side">
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
      </view>

      <view class="section-title">
        章节列表（{{ chapterCount }}）
        <!-- 排序切换：只影响本页视图；偏好记在本地（见 script 里的 ORDER_KEY）。
             靠 margin-left:auto 贴到标题行右侧 —— `.section-title` 是全局样式，别改它。 -->
        <view class="order-tabs">
          <button
            v-for="o in ORDERS"
            :key="o.value"
            class="order-tab u-button"
            :class="{ on: chapterOrder === o.value }"
            @click="setOrder(o.value)"
          >{{ o.label }}</button>
        </view>
      </view>
      <view class="chapters">
        <button
          v-for="(ch, i) in sortedChapters"
          :key="ch.id"
          class="chapter u-button"
          :title="ch.title"
          @click="read(ch)"
        >
          <text class="no u-span">{{ i + 1 }}</text>
          <text class="name u-span">{{ ch.title }}</text>
          <!-- 「最近一批入库」的角标（口径见后端 services.chapters.mark_latest_batch）。
               角标绝对定位在按钮内部 —— 见下方 .new 的注释（内缩是为了不跟相邻格子打架，
               不是因为会被裁）。 -->
          <text v-if="ch.isNew" class="new u-span">NEW</text>
        </button>
      </view>

      <!-- ============ 评论区 ============
           列表**任何人可看**；发表要登录；「删除」只给管理员看（真门在后端 require_admin）。

           ⚠️ **关闭时整块不渲染**（连「评论（N）」标题一起）—— 2026-10-09 用户明确：
           「关闭评论区是把整个评论区都屏蔽掉，而不是单单收起输入框」。
           所以下面没有"已关闭"的占位提示：那一块根本不存在。
           开关状态来自列表接口的 `enabled`（全站总开关 AND 单作品开关），
           所以即使关着也要先拉一次 —— 但拉回来只是**用来判断要不要渲染**。 -->
      <view v-if="commentEnabled" class="comment-block">
        <view class="section-title">评论（{{ commentTotal }}）</view>
        <view class="comments">
          <view v-if="isLoggedIn" class="c-editor">
            <textarea
              class="c-input"
              v-model="commentDraft"
              :maxlength="500"
              placeholder="说点什么…（最多 500 字）"
            />
            <view class="c-editor-foot">
              <text class="c-count u-span">{{ commentDraft.length }}/500</text>
              <button
                class="btn u-button"
                :disabled="commentSending || !commentDraft.trim()"
                @click="sendComment"
              >{{ commentSending ? '发表中…' : '发表' }}</button>
            </view>
          </view>

          <view v-else class="c-hint u-p">
            登录后可评论 —
            <text class="u-a" @click="gotoLoginForComment">去登录</text>
          </view>

          <view v-if="commentNotice" class="c-notice u-p">{{ commentNotice }}</view>

          <view v-if="!comments.length" class="c-hint u-p">还没有评论，来说两句</view>
          <view v-for="c in comments" :key="c.id" class="c-item">
            <view class="c-head">
              <text class="c-author u-span">{{ c.author }}</text>
              <text class="c-time u-span">{{ fmtCommentTime(c.createdAt) }}</text>
              <text v-if="isAdmin" class="c-del u-span" @click="removeComment(c.id)">删除</text>
            </view>
            <view class="c-body u-p">{{ c.content }}</view>
          </view>

          <button
            v-if="hasMoreComments"
            class="btn ghost u-button c-more"
            :disabled="commentLoading"
            @click="loadComments(true)"
        >{{ commentLoading ? '加载中…' : `加载更多（还有 ${commentTotal - comments.length} 条）` }}</button>
        </view>
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

/* 章节排序切换（倒序 / 正序）：贴在「章节列表（N）」这行右侧。
   ⚠️ `.section-title` 是**全局**样式（`src/style.css`），别去改它 ——
   这里只给自己的控件加 `margin-left: auto` 把它顶到行尾，全局那份不受影响。
   视觉沿用 `components/FilterBar.vue` 的芯片语言（细边框 + 选中态主题色）。 */
.order-tabs { margin-left: auto; display: flex; align-items: center; gap: 6px; }
.order-tab {
  border: 1px solid var(--border);
  background: var(--card);
  padding: 3px 10px;
  border-radius: 8px;
  font-size: 12px;
  font-weight: 600;
  color: var(--text-2);
  cursor: pointer;
  transition: all 0.15s;
}
.order-tab:hover { border-color: var(--primary); color: var(--primary); }
.order-tab.on { background: var(--primary-soft); color: var(--primary); border-color: var(--primary); font-weight: 700; }

/* 章节：每行 4 个。列宽只剩 ~80px，序号徽标要占掉一半宽度 → 隐藏，只留标题
   （标题本身就是「第 12 话」这样的短语），居中排布。 */
.chapters {
  display: grid;
  /* ⚠️ 必须 `minmax(0, 1fr)`，不能只写 `1fr`：grid 子项（uni-button）默认 `min-width: auto`，
     而 `1fr` 轨道的下限就是子项的 min-content —— 章节名里存在「第2回官方人气投票结果」
     「单行本第6卷特典」这类长标题、且 `.name` 是 nowrap，轨道会被撑成不等宽
     （实测 100.7 / 136.7 / 100.7 / 106px），4 列合计 468px > 容器 353px → **整页横向溢出**
     （393px 视口下 scrollWidth 484 vs clientWidth 385）。
     `minmax(0, …)` 允许轨道收缩到 0，超长标题交给 `.name` 已有的 overflow:hidden + ellipsis 截断。 */
  grid-template-columns: repeat(4, minmax(0, 1fr));
  gap: 8px;
}
.chapter {
  /* uni-button 基础样式已是 relative（角标靠它定位），这里显式写一遍免得日后被覆盖 */
  position: relative;
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

/* 「最近一批入库」角标：贴按钮**内**右上角的小胶囊。
   ⚠️ 内缩是**为了不跟相邻格子打架**，不是被裁 —— uni 自带的 `uni-button { overflow: hidden }`
   已被兼容层覆盖成 `visible`（见 `src/uni-compat.css`，那条是为了不裁消息铃铛的红点），
   实测 `.chapter` 的 computed `overflow` 就是 `visible`。
   （4 列网格 gap 只有 8px，角标外扩会与邻格贴到一起。）
   尺寸压到「只占顶部那 9px 内边距」：角标绝对定位、不参与布局，
   标题的居中位置与不带角标时**完全一致**（早前一版给标题加 padding-right 让位，
   结果所有标题整体左移，与未标章节对不齐，已改掉）。
   `pointer-events: none` 保证点角标等于点整颗按钮，不另开热区。

   ⚠️ **点过的章节照样显示 NEW，这是刻意的**（2026-10-09 用户确认）：角标表示
   「这章属于该作品最近一批入库的章节」，**与有没有读过无关**；要等该作品来了
   下一批新章节，这批的角标才一起让位。别把它改成"读过即消失"。 */
.new {
  position: absolute;
  top: 1px;
  right: 2px;
  padding: 0 2px;
  border-radius: 999px;
  background: var(--primary);
  color: #fff;
  font-size: 7px;
  line-height: 10px;
  font-weight: 700;
  pointer-events: none;
}

/* ---- 下架 / 不存在（详情接口 404）---- */
.back-home { margin-top: 14px; padding: 7px 16px; font-size: 13px; }

/* ---- 评论区 ---- */
.comments { display: flex; flex-direction: column; gap: 10px; }

/* 输入框：uni 的 <textarea> 会渲染成 <uni-textarea>，内层才是原生 textarea ——
   边框/圆角/背景写在包裹元素上即可（与 pages/admin/index.vue 的 .u-textarea 同一套做法） */
.c-input {
  width: 100%;
  box-sizing: border-box;
  min-height: 74px;
  padding: 8px 10px;
  border: 1px solid var(--border);
  border-radius: 10px;
  background: var(--card);
  color: var(--text);
  font-size: 13px;
  font-family: inherit;
}
.c-editor-foot { display: flex; align-items: center; gap: 10px; margin-top: 8px; }
.c-count { font-size: 12px; color: var(--text-2); }
.c-editor-foot .btn { margin-left: auto; padding: 6px 16px; font-size: 13px; }

/* 关闭态 / 空态 / 未登录提示 —— 同一种"低调说明"的语汇 */
.c-hint { font-size: 13px; color: var(--text-2); padding: 10px 12px; background: var(--mute); border-radius: 10px; }
.c-notice { font-size: 13px; color: var(--primary-dark); background: var(--primary-soft); border-radius: 8px; padding: 8px 12px; }

.c-item { background: var(--card); border: 1px solid var(--border); border-radius: 10px; padding: 10px 12px; }
.c-head { display: flex; align-items: center; gap: 8px; }
.c-author { font-size: 13px; font-weight: 700; color: var(--text); }
.c-time { font-size: 12px; color: var(--text-2); }
/* 删除：只有管理员看得到（后端还会再判一次权限） */
.c-del { margin-left: auto; font-size: 12px; color: var(--text-2); cursor: pointer; }
.c-del:hover { color: #c0392b; }
.c-body { margin-top: 4px; font-size: 14px; line-height: 1.7; color: var(--text); word-break: break-word; }

.c-more { align-self: center; padding: 7px 18px; font-size: 13px; margin-top: 2px; }

/* #ifdef H5 */
/* ==================== 网页版（.mode-web，2026-10-10） ====================
   两栏：左栏（作品卡 + 简介，sticky 跟随）+ 右栏（章节 / 评论）。
   移动端为基准，这里全部是增量覆盖；整段只进 H5 产物（小程序恒移动版）。 */
.mode-web .detail {
  display: grid;
  grid-template-columns: 340px minmax(0, 1fr);
  column-gap: 24px;
  align-items: start;
}
/* 左栏整体 sticky：章节列表很长，滚动时封面 / 简介保持可见。
   `top: 84px` = 顶栏 64px + 20px 呼吸位。 */
.mode-web .side { grid-column: 1; grid-row: 1 / span 3; position: sticky; top: 84px; }

/* 左栏作品卡：改**纵向**（封面居中放大、信息在下）—— 340px 的窄栏里横向摆不开 */
.mode-web .hero { flex-direction: column; align-items: stretch; gap: 14px; padding: 16px; }
.mode-web .hero-cover { width: 180px; height: 240px; margin: 0 auto; }
.mode-web .hero-info .u-h1 { font-size: 20px; margin-bottom: 8px; }
.mode-web .hero-line { font-size: 13px; }
.mode-web .actions { margin-top: 14px; }
.mode-web .actions .btn { flex: 1 1 auto; padding: 9px 14px; font-size: 14px; }
.mode-web .desc { padding: 12px 14px; }

/* 右栏：章节列表标题对齐左栏顶、章节网格 4 列 → 6 列 */
.mode-web .detail > .section-title { grid-column: 2; grid-row: 1; margin-top: 0; }
.mode-web .chapters { grid-column: 2; grid-row: 2; grid-template-columns: repeat(6, minmax(0, 1fr)); }
.mode-web .comment-block { grid-column: 2; grid-row: 3; }
/* 评论一行别太长（右栏 ~816px 全宽会超出阅读舒适区） */
.mode-web .comments { max-width: 680px; }

/* 中窄宽窗（≤1024px）：左栏收窄、章节降回 4 列 */
@media (max-width: 1024px) {
  .mode-web .detail { grid-template-columns: 280px minmax(0, 1fr); }
  .mode-web .chapters { grid-template-columns: repeat(4, minmax(0, 1fr)); }
}
/* 窄窗（≤860px）：退回单栏流（与移动端同序：作品卡 → 简介 → 章节 → 评论） */
@media (max-width: 860px) {
  .mode-web .detail { display: block; }
  .mode-web .side { position: static; }
  .mode-web .detail > .section-title { margin-top: 28px; }
}
/* #endif */
</style>
