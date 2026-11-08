<script setup>
import { ref } from 'vue'
import { api } from '../api'
import { MODE_OPTIONS } from '../modes'
import ModeHint from './ModeHint.vue'

const mode = ref('hybrid')
const loading = ref(false)
const error = ref('')
const summary = ref(null)
const cases = ref([])

async function run() {
  if (loading.value) return
  loading.value = true
  error.value = ''
  summary.value = null
  cases.value = []
  try {
    const data = await api.eval(mode.value)
    summary.value = data.summary
    cases.value = data.cases
  } catch (e) {
    error.value = e.message
  } finally {
    loading.value = false
  }
}

const pct = (v) => (v * 100).toFixed(1) + '%'
const rankClass = (rank) => (rank === 1 ? 'ok' : rank ? 'mid' : 'bad')
</script>

<template>
  <section>
    <div class="row">
      <select v-model="mode">
        <option v-for="m in MODE_OPTIONS" :key="m.key" :value="m.key">{{ m.label }}</option>
      </select>
      <button :disabled="loading" @click="run">
        {{ loading ? '评测中…' : '跑 20 条黄金题' }}
      </button>
      <span class="muted" style="font-size: 12px">首次会加载模型，约 1~2 秒</span>
    </div>

    <ModeHint :mode="mode" compact />

    <p v-if="error" class="bad">评测失败：{{ error }}</p>

    <div v-if="summary" class="kpis">
      <div class="kpi">
        <div class="v">{{ pct(summary.recall) }}</div>
        <div class="l">Recall@{{ summary.k }}</div>
      </div>
      <div class="kpi">
        <div class="v">{{ summary.mrr.toFixed(3) }}</div>
        <div class="l">MRR@{{ summary.k }}</div>
      </div>
      <div class="kpi">
        <div class="v">{{ summary.ndcg.toFixed(3) }}</div>
        <div class="l">nDCG@{{ summary.k }}</div>
      </div>
      <div class="kpi">
        <div class="v">{{ pct(summary.top1) }}</div>
        <div class="l">Top-1</div>
      </div>
      <div class="kpi">
        <div class="v">{{ summary.miss }} 条</div>
        <div class="l">未命中</div>
      </div>
    </div>

    <table v-if="cases.length">
      <thead>
        <tr>
          <th>#</th>
          <th>问题</th>
          <th>名次</th>
          <th>RR</th>
          <th>nDCG</th>
          <th>Top-1 命中</th>
        </tr>
      </thead>
      <tbody>
        <tr v-for="(c, i) in cases" :key="c.query">
          <td class="num">{{ i + 1 }}</td>
          <td>{{ c.query }}</td>
          <td class="num" :class="rankClass(c.rank)">{{ c.rank ?? '—' }}</td>
          <td class="num">{{ c.rr.toFixed(3) }}</td>
          <td class="num">{{ c.ndcg.toFixed(3) }}</td>
          <td>
            <template v-if="c.hits[0]">
              {{ c.hits[0].path }} <span class="muted">› {{ c.hits[0].heading }}</span>
            </template>
            <span v-else class="muted">—</span>
          </td>
        </tr>
      </tbody>
    </table>
  </section>
</template>

<style scoped>
.kpis {
  display: flex;
  gap: 12px;
  flex-wrap: wrap;
  margin: 12px 0 16px;
}
.kpi {
  background: var(--panel);
  border: 1px solid var(--line);
  border-radius: 10px;
  padding: 10px 16px;
  min-width: 110px;
}
.kpi .v {
  font-size: 20px;
  font-weight: 600;
  font-variant-numeric: tabular-nums;
}
.kpi .l {
  color: var(--dim);
  font-size: 12px;
}
</style>
