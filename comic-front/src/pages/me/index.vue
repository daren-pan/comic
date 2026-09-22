<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { storeToRefs } from 'pinia'
import { getFavorites, getHistoryWithDetail, removeHistory } from '../../api'
import { useUserStore } from '../../stores/user'
import type { Comic, HistoryEntry } from '../../types'
import { onLoad } from '@dcloudio/uni-app'
import { openNewTab, setRoute, useRouter } from '../../utils/router'
import Layout from '../../components/Layout.vue'

const router = useRouter()
const favorites = ref<Comic[]>([])
const history = ref<(HistoryEntry & { comic?: Comic; chapterTitle?: string })[]>([])
const loaded = ref(false)
const tab = ref<'history' | 'favorites'>('history')
const { isLoggedIn: logged } = storeToRefs(useUserStore())

function fmtTime(iso: string): string {
  const d = new Date(iso)
  const pad = (n: number) => String(n).padStart(2, '0')
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())} ${pad(d.getHours())}:${pad(d.getMinutes())}`
}

async function refresh() {
  const [favs, his] = await Promise.all([
    logged.value ? getFavorites() : Promise.resolve([]),
    getHistoryWithDetail(),
  ])
  favorites.value = favs
  history.value = his
  loaded.value = true
}

onMounted(refresh)

async function onRemove(comicId: number) {
  await removeHistory(comicId)
  history.value = history.value.filter((h) => h.comicId !== comicId)
}

function continueRead(h: HistoryEntry) {
  // 新标签页打开阅读器，书架保留在当前标签页（与详情页点章节的行为一致）
  // H5 开新标签，小程序 / App 退化为同页跳转（见 utils/router.openNewTab）
  openNewTab(`/reader/${h.comicId}/${h.chapterId}`)
}
// uni 页面生命周期：登记该页对应的 web 路径（替代 vue-router 的路由状态）
onLoad((options) => setRoute('/me', options ?? {}))

</script>

<template>
  <Layout>
    <view>
      <view class="section-title">我的书架</view>

      <view class="tabs">
        <button class="u-button" :class="{ on: tab === 'history' }" @click="tab = 'history'">最近阅读</button>
        <button class="u-button" :class="{ on: tab === 'favorites' }" @click="tab = 'favorites'">我的收藏</button>
      </view>

      <view v-if="!loaded" class="empty">加载中…</view>

      <!-- 最近阅读 -->
      <view v-else-if="tab === 'history'">
        <view v-if="history.length === 0" class="empty">还没有阅读记录，去首页找一本看看吧</view>
        <view v-else class="list">
          <view v-for="h in history" :key="h.comicId" class="row" @click="continueRead(h)">
            <image mode="aspectFill" class="row-cover u-img" :src="h.comic?.cover" :alt="h.comic?.title" />
            <view class="row-main">
              <view class="u-h4">{{ h.comic?.title }}</view>
              <view class="row-sub u-p">{{ h.chapterTitle }}</view>
              <view class="row-sub dim u-p">读到第 {{ h.pageNo }} 页 · {{ fmtTime(h.readAt) }}</view>
            </view>
            <view class="row-actions" @click.stop>
              <button class="btn ghost sm u-button" @click="continueRead(h)">续读</button>
              <button class="btn ghost sm danger u-button" @click="onRemove(h.comicId)">删除</button>
            </view>
          </view>
        </view>
      </view>

      <!-- 收藏 -->
      <view v-else>
        <view v-if="!logged" class="fav-login">
          <view class="u-p">收藏需要登录，登录后可跨设备同步</view>
          <button class="btn u-button" @click="router.push('/login')">去登录</button>
        </view>
        <view v-else-if="favorites.length === 0" class="empty">还没有收藏，详情页点「收藏」即可加入书架</view>
        <view v-else class="fav-grid">
          <view v-for="c in favorites" :key="c.id" class="fav-item" @click="router.push(`/comic/${c.id}`)">
            <view class="fav-thumb">
              <image mode="aspectFill" class="u-img" :src="c.cover" :alt="c.title" />
            </view>
            <view class="u-p">{{ c.title }}</view>
            <text class="u-span">{{ c.chapterCount }} 话</text>
          </view>
        </view>
      </view>
    </view>
  </Layout>
</template>

<style scoped>
.tabs { display: flex; gap: 8px; margin-bottom: 16px; }
.tabs .u-button {
  border: 1px solid var(--border);
  background: #fff;
  padding: 7px 20px;
  border-radius: 999px;
  font-size: 14px;
  cursor: pointer;
  font-weight: 600;
  color: var(--text-2);
}
.tabs .u-button.on { background: var(--primary); border-color: var(--primary); color: #fff; }

.list { display: flex; flex-direction: column; gap: 10px; }
.row {
  display: flex;
  align-items: center;
  gap: 14px;
  background: #fff;
  border: 1px solid var(--border);
  border-radius: 12px;
  padding: 10px 14px;
  cursor: pointer;
  transition: all 0.15s;
}
.row:hover { border-color: var(--primary); box-shadow: var(--shadow-hover); transform: translateY(-1px); }
.row-cover { width: 54px; height: 72px; border-radius: 8px; object-fit: cover; }
.row-main { flex: 1; min-width: 0; }
.row-main .u-h4 { margin: 0; font-size: 15px; }
.row-sub { margin: 2px 0 0; font-size: 13px; color: var(--primary); }
.row-sub.dim { color: var(--text-2); }
.row-actions { display: flex; gap: 8px; }
.btn.sm { padding: 5px 12px; font-size: 13px; }
.btn.danger:hover { border-color: #e23; color: #e23; }

.fav-grid { display: grid; grid-template-columns: repeat(6, 1fr); gap: 14px; }
.fav-login {
  text-align: center;
  background: #fff;
  border: 1px solid var(--border);
  border-radius: 12px;
  padding: 48px 20px;
  color: var(--text-2);
}
.fav-login .u-p { margin: 0 0 16px; font-size: 14px; }
.fav-item {
  background: #fff;
  border-radius: 12px;
  overflow: hidden;
  cursor: pointer;
  box-shadow: var(--shadow);
  transition: all 0.15s;
  text-align: center;
  padding-bottom: 8px;
}
.fav-item:hover { transform: translateY(-3px); box-shadow: var(--shadow-hover); }
/* 封面 3:4 比例盒：不用 aspect-ratio（小程序 WebView 视基础库版本而定），
   用「高度 0 + padding-bottom 撑比例」（padding 百分比按包含块**宽度**解析）。 */
.fav-thumb { position: relative; height: 0; padding-bottom: 133.33%; background: #eee; }
.fav-thumb .u-img { position: absolute; top: 0; left: 0; width: 100%; height: 100%; object-fit: cover; display: block; }
.fav-item .u-p { margin: 6px 0 0; font-size: 13px; font-weight: 600; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; padding: 0 6px; }
.fav-item .u-span { font-size: 12px; color: var(--text-2); }

@media (max-width: 900px) {
  .fav-grid { grid-template-columns: repeat(4, 1fr); }
  .row-actions { flex-direction: column; }
}
@media (max-width: 560px) {
  .fav-grid { grid-template-columns: repeat(3, 1fr); }
}
</style>
