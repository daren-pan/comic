<script setup lang="ts">
// 最近更新 —— 按 updatedAt 倒序列出源站刚同步过的漫画（后端 sort=updated）
import { onMounted, ref } from 'vue'
import { getComics } from '../../api'
import type { Comic } from '../../types'
import ComicCard from '../../components/ComicCard.vue'
import { onLoad } from '@dcloudio/uni-app'
import { setRoute } from '../../utils/router'
import Layout from '../../components/Layout.vue'

const pageSize = 20

const comics = ref<Comic[]>([])
const total = ref(0)
const page = ref(1)
const loading = ref(false)

/** 相对时间，作为封面角标显示在卡片右上角 */
function fmtTime(iso: string): string {
  const diff = Date.now() - new Date(iso).getTime()
  const mins = Math.floor(diff / 60000)
  if (mins < 1) return '刚刚'
  if (mins < 60) return `${mins} 分钟前`
  const hours = Math.floor(mins / 60)
  if (hours < 24) return `${hours} 小时前`
  const days = Math.floor(hours / 24)
  if (days < 30) return `${days} 天前`
  const d = new Date(iso)
  const pad = (n: number) => String(n).padStart(2, '0')
  return `${pad(d.getMonth() + 1)}-${pad(d.getDate())}`
}

async function load() {
  loading.value = true
  try {
    const res = await getComics({ sort: 'updated', page: page.value, pageSize })
    comics.value = res.items
    total.value = res.total
  } catch {
    comics.value = []
    total.value = 0
  } finally {
    loading.value = false
  }
}

function totalPages(): number {
  return Math.max(1, Math.ceil(total.value / pageSize))
}

function go(p: number) {
  page.value = p
  load()
}

onMounted(load)
// uni 页面生命周期：登记该页对应的 web 路径（替代 vue-router 的路由状态）
onLoad((options) => setRoute('/latest', options ?? {}))

</script>

<template>
  <Layout>
    <view>
      <view class="section-title">⚡ 最近更新</view>
      <view class="lead u-p">源站一更新，这里几分钟可见 —— 按最近更新时间倒序排列，共 {{ total }} 部。</view>

      <view v-if="loading" class="empty">加载中…</view>
      <view v-else-if="comics.length === 0" class="empty">暂无更新记录</view>
      <view v-else class="grid">
        <ComicCard v-for="c in comics" :key="c.id" :comic="c" :time="fmtTime(c.updatedAt)" />
      </view>

      <view v-if="totalPages() > 1" class="pager">
        <button class="btn ghost u-button" :disabled="page <= 1" @click="go(page - 1)">上一页</button>
        <text class="page-info u-span">{{ page }} / {{ totalPages() }}</text>
        <button class="btn ghost u-button" :disabled="page >= totalPages()" @click="go(page + 1)">下一页</button>
      </view>
    </view>
  </Layout>
</template>

<style scoped>
.lead { color: var(--text-2); font-size: 14px; margin: -8px 0 18px; }

.grid { display: grid; grid-template-columns: repeat(5, 1fr); gap: 16px; }
@media (max-width: 900px) { .grid { grid-template-columns: repeat(3, 1fr); } }
/* 手机（≤560px）保持 3 列，只收紧间距（原先降到 2 列；2026-09-22 用户要求） */
@media (max-width: 560px) { .grid { gap: 10px; } }

.pager { display: flex; align-items: center; justify-content: center; gap: 16px; margin-top: 26px; }
.page-info { color: var(--text-2); font-size: 14px; }
</style>
