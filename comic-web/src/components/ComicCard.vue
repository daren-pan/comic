<script setup lang="ts">
import type { Comic } from '../types'

defineProps<{ comic: Comic }>()
</script>

<template>
  <RouterLink :to="`/comic/${comic.id}`" class="card">
    <div class="cover">
      <img :src="comic.cover" :alt="comic.title" loading="lazy" />
      <span class="status" :class="{ done: comic.status === '已完结' }">{{ comic.status }}</span>
    </div>
    <div class="info">
      <h3 class="title">{{ comic.title }}</h3>
      <p class="meta">{{ comic.author }}</p>
      <p class="update">{{ comic.latestChapterTitle }}</p>
    </div>
  </RouterLink>
</template>

<style scoped>
.card {
  display: block;
  background: var(--card);
  border-radius: var(--radius);
  overflow: hidden;
  box-shadow: var(--shadow);
  transition: transform 0.18s, box-shadow 0.18s;
}
.card:hover { transform: translateY(-4px); box-shadow: var(--shadow-hover); }

.cover { position: relative; aspect-ratio: 3 / 4; background: #eee; }
.cover img { width: 100%; height: 100%; object-fit: cover; display: block; }

.status {
  position: absolute;
  top: 8px;
  left: 8px;
  font-size: 11px;
  padding: 2px 8px;
  border-radius: 999px;
  background: rgba(255, 90, 54, 0.92);
  color: #fff;
  font-weight: 700;
}
.status.done { background: rgba(90, 90, 90, 0.85); }

.info { padding: 10px 12px 12px; }
.title {
  margin: 0;
  font-size: 15px;
  font-weight: 700;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}
.meta { margin: 2px 0 0; font-size: 12px; color: var(--text-2); }
.update { margin: 6px 0 0; font-size: 12px; color: var(--primary); white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
</style>
