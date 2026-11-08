<script setup>
import { ref } from 'vue'
import { api } from '../api'
import { MODE_OPTIONS } from '../modes'
import HitCard from './HitCard.vue'
import ModeHint from './ModeHint.vue'

const query = ref('')
const mode = ref('hybrid')
const topK = ref(5)
const kind = ref('')
const module = ref('')

const loading = ref(false)
const error = ref('')
const result = ref(null)

async function run() {
  const q = query.value.trim()
  if (!q || loading.value) return
  loading.value = true
  error.value = ''
  result.value = null
  try {
    result.value = await api.search({
      query: q,
      mode: mode.value,
      top_k: Number(topK.value) || 5,
      kind: kind.value.trim() || null,
      module: module.value.trim() || null,
    })
  } catch (e) {
    error.value = e.message
  } finally {
    loading.value = false
  }
}
</script>

<template>
  <section>
    <div class="row">
      <input
        v-model="query"
        type="text"
        class="grow"
        placeholder="输入问题，回车检索（例：某模块为什么独立进程）"
        @keyup.enter="run"
      />
      <select v-model="mode">
        <option v-for="m in MODE_OPTIONS" :key="m.key" :value="m.key">{{ m.label }}</option>
      </select>
      <input v-model="topK" type="number" min="1" max="20" style="width: 70px" />
      <button :disabled="loading || !query.trim()" @click="run">
        {{ loading ? '检索中…' : '检索' }}
      </button>
    </div>

    <ModeHint :mode="mode" />

    <div class="row muted" style="font-size: 12px">
      <span>kind</span>
      <input v-model="kind" type="text" placeholder="module_readme / schema…" style="flex: 0 1 220px" />
      <span>module</span>
      <input v-model="module" type="text" placeholder="crawler / api…" style="flex: 0 1 180px" />
    </div>

    <p v-if="error" class="bad">检索失败：{{ error }}</p>

    <template v-if="result">
      <p class="muted">
        {{ result.count }} 条命中 · 候选 语义 {{ result.candidates.vector }} / 字面
        {{ result.candidates.lexical }} · {{ result.elapsed_ms }}ms
      </p>
      <HitCard
        v-for="(hit, i) in result.hits"
        :key="hit.doc_id"
        :hit="hit"
        :index="i + 1"
        :mode="mode"
      />
      <p v-if="!result.hits.length" class="muted">没有命中</p>
    </template>
  </section>
</template>

<style scoped>
.grow {
  flex: 1;
  min-width: 280px;
}
</style>
