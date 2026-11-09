<script setup>
import { computed, ref } from 'vue'
import { api } from '../api'
import { MODE_OPTIONS } from '../modes'
import HitCard from './HitCard.vue'
import ModeHint from './ModeHint.vue'

const query = ref('')
const mode = ref('hybrid')
const topK = ref(5)
const kind = ref('')
const module = ref('')

// 融合参数：只有混合检索用得上。
// 默认值与后端 config.RRF_K / RRF_WEIGHTS 保持一致；**只有用户改过才发送覆盖**，
// 否则页面就成了"每次都偷偷用旧默认值打后端"（曾经踩过：界面默认 0.75/0.25，
// 导致后端明明改成等权，页面上仍然按 0.75/0.25 算）。
const DEFAULT_K = 3
const DEFAULT_SEM = 1
const DEFAULT_LEX = 1
const showFusion = ref(false)
const rrfK = ref(DEFAULT_K)
const rrfSem = ref(DEFAULT_SEM)
const rrfLex = ref(DEFAULT_LEX)

const fusionDirty = computed(
  () =>
    Number(rrfK.value) !== DEFAULT_K ||
    Number(rrfSem.value) !== DEFAULT_SEM ||
    Number(rrfLex.value) !== DEFAULT_LEX,
)

// 耗时展示：常规 <300ms 绿色、<1500ms 黄色、再慢红色。
const elapsedText = computed(() => {
  const ms = result.value?.elapsed_ms ?? 0
  return ms >= 1000 ? `${(ms / 1000).toFixed(2)} s` : `${ms} ms`
})
const speedClass = computed(() => {
  const ms = result.value?.elapsed_ms ?? 0
  return ms < 300 ? 'fast' : ms < 1500 ? 'mid' : 'slow'
})
// 分段：常规是 向量/字面/融合；深度是 改写/检索/重排。
const timingText = computed(() => {
  const t = result.value?.timings
  if (!t) return ''
  if (result.value.route === 'deep') {
    return `分段：改写 ${t.rewrite}ms · 检索 ${t.search}ms · 重排 ${t.rerank}ms`
  }
  return `分段：向量 ${t.vector}ms · 字面 ${t.lexical}ms · 融合 ${t.fusion}ms`
})

function resetFusion() {
  rrfK.value = DEFAULT_K
  rrfSem.value = DEFAULT_SEM
  rrfLex.value = DEFAULT_LEX
}

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
    const payload = {
      query: q,
      mode: mode.value,
      top_k: Number(topK.value) || 5,
      kind: kind.value.trim() || null,
      module: module.value.trim() || null,
    }
    // 只有用户**真的改过**融合参数才覆盖后端默认值
    if (mode.value === 'hybrid' && fusionDirty.value) {
      payload.rrf_k = Number(rrfK.value)
      payload.rrf_semantic_weight = Number(rrfSem.value)
      payload.rrf_lexical_weight = Number(rrfLex.value)
    }
    result.value = await api.search(payload)
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
      <a v-if="mode === 'hybrid'" href="#" @click.prevent="showFusion = !showFusion">
        {{ showFusion ? '收起融合参数' : '融合参数' }}{{ fusionDirty ? ' · 已改' : '' }}
      </a>
    </div>

    <div v-if="showFusion && mode === 'hybrid'" class="fusion">
      <label>
        k
        <input v-model="rrfK" type="number" min="0" max="200" step="1" />
      </label>
      <label>
        语义权重
        <input v-model="rrfSem" type="number" min="0" max="1" step="0.05" />
      </label>
      <label>
        字面权重
        <input v-model="rrfLex" type="number" min="0" max="1" step="0.05" />
      </label>
      <a href="#" @click.prevent="resetFusion">恢复默认</a>
      <span class="muted note">
        score = Σ 权重 / (k + 名次)。k 越大，"两路都靠后"越吃香。
      </span>
    </div>

    <p v-if="error" class="bad">检索失败：{{ error }}</p>

    <template v-if="result">
      <div class="stats">
        <span class="time" :class="speedClass">{{ elapsedText }}</span>
        <span class="muted">{{ result.count }} 条命中</span>
        <span v-if="result.route === 'deep'" class="badge deep">深度路径（改写+重排）</span>
        <span v-else class="badge">常规路径</span>
        <span class="muted">类型 {{ result.query_type }}</span>
        <span class="muted">候选 语义 {{ result.candidates?.vector ?? '-' }} / 字面 {{ result.candidates?.lexical ?? '-' }}</span>
        <template v-if="mode === 'hybrid' && result.rrf">
          <span class="muted">融合 k={{ result.rrf.k }} · 权重 {{ result.rrf.weights.join(' / ') }}</span>
        </template>
      </div>
      <p v-if="timingText" class="muted detail">{{ timingText }}</p>
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
.fusion {
  display: flex;
  gap: 16px;
  flex-wrap: wrap;
  align-items: center;
  margin-top: 6px;
  padding: 8px 12px;
  border: 1px solid var(--line);
  border-radius: 8px;
  font-size: 12px;
}
.fusion label {
  display: flex;
  gap: 6px;
  align-items: center;
}
.fusion input {
  width: 74px;
}
.fusion .note {
  flex-basis: 100%;
}
.stats {
  display: flex;
  gap: 12px;
  align-items: center;
  flex-wrap: wrap;
  margin-top: 10px;
  font-size: 12px;
}
.time {
  font-variant-numeric: tabular-nums;
  font-weight: 600;
  padding: 2px 8px;
  border-radius: 6px;
  border: 1px solid var(--line);
}
.time.fast {
  color: #3fb950;
}
.time.mid {
  color: #d29922;
}
.time.slow {
  color: #f85149;
}
.badge {
  padding: 1px 8px;
  border-radius: 999px;
  border: 1px solid var(--line);
  color: var(--dim);
}
.badge.deep {
  color: #d29922;
  border-color: #d29922;
}
.detail {
  margin-top: 4px;
  font-size: 11px;
}
</style>
