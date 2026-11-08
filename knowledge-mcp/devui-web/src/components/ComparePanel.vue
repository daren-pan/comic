<script setup>
import { ref } from 'vue'
import { api } from '../api'
import { MODES } from '../modes'
import ModeHint from './ModeHint.vue'

const query = ref('')
const topK = ref(5)
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
    result.value = await api.compare({ query: q, top_k: Number(topK.value) || 5 })
  } catch (e) {
    error.value = e.message
  } finally {
    loading.value = false
  }
}

const fmt = (v, d = 4) => (v === null || v === undefined ? '—' : Number(v).toFixed(d))
</script>

<template>
  <section>
    <div class="row">
      <input
        v-model="query"
        type="text"
        class="grow"
        placeholder="同一个问题，三种模式并排对比"
        @keyup.enter="run"
      />
      <input v-model="topK" type="number" min="1" max="20" style="width: 70px" />
      <button :disabled="loading || !query.trim()" @click="run">
        {{ loading ? '对比中…' : '对比' }}
      </button>
    </div>

    <p v-if="error" class="bad">对比失败：{{ error }}</p>

    <p v-if="!result" class="muted" style="font-size: 12px">
      同一个问题分别用三种模式跑一遍：左列只看语义，中列只看字面，右列按名次融合。
      三列的第一名不同，就说明这两种信号在打架。
    </p>

    <div v-if="result" class="cols">
      <div v-for="m in MODES" :key="m.key">
        <ModeHint :mode="m.key" compact />
        <template v-if="result[m.key]?.hits?.length">
          <div
            v-for="(hit, i) in result[m.key].hits.slice(0, 5)"
            :key="hit.doc_id + i"
            class="mini"
          >
            <div class="mini-top">
              <span class="num muted">#{{ i + 1 }}</span>
              <span class="path">{{ hit.path }}</span>
            </div>
            <div class="mini-meta">
              <span>score {{ fmt(hit.score) }}</span>
              <span>语义 {{ fmt(hit.vector_score, 3) }}</span>
              <span>字面 {{ fmt(hit.lexical_score, 2) }}</span>
            </div>
            <div class="muted ellipsis">{{ hit.heading }}</div>
          </div>
        </template>
        <p v-else class="muted">无命中</p>
      </div>
    </div>
  </section>
</template>

<style scoped>
.grow {
  flex: 1;
  min-width: 280px;
}
.cols {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: 12px;
}
h3 {
  font-size: 13px;
  color: var(--dim);
  margin: 0 0 8px;
}
.mini {
  border: 1px solid var(--line);
  border-radius: 8px;
  background: var(--panel);
  padding: 8px 10px;
  margin-bottom: 8px;
}
.mini-top {
  display: flex;
  gap: 8px;
  align-items: baseline;
}
.path {
  color: var(--accent);
  font-weight: 600;
  font-size: 13px;
  word-break: break-all;
}
.mini-meta {
  display: flex;
  gap: 10px;
  flex-wrap: wrap;
  color: var(--dim);
  font-size: 11px;
  margin-top: 2px;
}
.ellipsis {
  font-size: 12px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
</style>
