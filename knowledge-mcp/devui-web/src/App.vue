<script setup>
import { ref } from 'vue'
import StatusBar from './components/StatusBar.vue'
import SearchPanel from './components/SearchPanel.vue'
import ComparePanel from './components/ComparePanel.vue'
import EvalPanel from './components/EvalPanel.vue'

const tabs = [
  { key: 'search', label: '搜索' },
  { key: 'compare', label: '三路对比' },
  { key: 'eval', label: '评测' },
]
const tab = ref('search')
</script>

<template>
  <header class="bar">
    <h1>知识库调试</h1>
    <StatusBar />
  </header>
  <main>
    <nav class="tabs">
      <button
        v-for="t in tabs"
        :key="t.key"
        class="tab"
        :class="{ on: tab === t.key }"
        @click="tab = t.key"
      >
        {{ t.label }}
      </button>
    </nav>
    <SearchPanel v-show="tab === 'search'" />
    <ComparePanel v-show="tab === 'compare'" />
    <EvalPanel v-show="tab === 'eval'" />
  </main>
</template>

<style scoped>
.bar {
  padding: 14px 20px;
  border-bottom: 1px solid var(--line);
  display: flex;
  gap: 16px;
  align-items: center;
  flex-wrap: wrap;
}
h1 {
  font-size: 16px;
  margin: 0;
  font-weight: 600;
}
main {
  padding: 18px 20px 60px;
  max-width: 1180px;
}
.tabs {
  display: flex;
  gap: 6px;
  margin-bottom: 16px;
}
.tab {
  padding: 7px 14px;
  border-radius: 8px;
  border: 1px solid var(--line);
  background: var(--panel);
  color: var(--dim);
  font-size: 13px;
  cursor: pointer;
}
.tab.on {
  color: var(--fg);
  border-color: var(--accent);
  background: var(--panel);
}
</style>
