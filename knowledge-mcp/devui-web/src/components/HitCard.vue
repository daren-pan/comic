<script setup>
import { computed, ref } from 'vue'
import { api } from '../api'
import { sourceLabel } from '../modes'

const props = defineProps({
  hit: { type: Object, required: true },
  index: { type: Number, required: true },
  expect: { type: Array, default: null },
  mode: { type: String, default: 'hybrid' },
})

// 分数构成：只在"向量那一路参与排序"的模式下展示。
// lexical 模式下 score 是 BM25，跟这套加权没关系，显示出来只会误导。
const boostInfo = computed(() => {
  const b = props.hit.boosts || {}
  if (props.mode === 'lexical' || !b.terms?.length) return null
  const heading = b.heading || {}
  const module = b.module || {}
  const body = b.body || {}
  const parts = [
    { key: '余弦', value: props.hit.vector_score, detail: '' },
    {
      key: '标题',
      value: heading.score,
      detail: heading.matched?.length
        ? `命中「${heading.matched.join('、')}」${heading.matched.length}/${heading.total} 词（0.12×${heading.matched.length}/${heading.total}）`
        : '未命中',
    },
    {
      key: '模块',
      value: module.score,
      detail: module.reason || '未命中',
    },
    {
      key: '正文',
      value: body.score,
      detail: body.matched?.length
        ? `命中「${body.matched.join('、')}」${body.matched.length}/${body.total} 词（0.08×${body.matched.length}/${body.total}）`
        : '未命中',
    },
  ]
  return {
    // ⚠️ 不能用 hit.score：hybrid 下那是 RRF 分，与这四项相加无关。
    total: parts.reduce((sum, p) => sum + p.value, 0),
    parts,
  }
})

const open = ref(false)
const loading = ref(false)
const section = ref(null)
const error = ref('')

async function toggleRead() {
  if (open.value) {
    open.value = false
    return
  }
  open.value = true
  if (section.value) return
  loading.value = true
  error.value = ''
  try {
    section.value = await api.section(props.hit.doc_id)
  } catch (e) {
    error.value = e.message
  } finally {
    loading.value = false
  }
}

// 把整节原文按"块区间"切片：块内正常，块间缝隙（标题行、空行）单独标灰。
const segments = computed(() => {
  const s = section.value
  if (!s?.blocks?.length) return []
  const blocks = s.blocks
    .filter((b) => b.start !== null && b.start !== undefined)
    .sort((a, b) => a.start - b.start)
  const out = []
  let cursor = 0
  for (const b of blocks) {
    if (b.start > cursor) out.push({ text: s.text.slice(cursor, b.start), cls: 'gap' })
    out.push({
      text: s.text.slice(b.start, b.end),
      cls: b.matched ? 'blk hit' : 'blk',
      no: b.index + 1,
      matched: b.matched,
    })
    cursor = Math.max(cursor, b.end)
  }
  if (cursor < s.text.length) out.push({ text: s.text.slice(cursor), cls: 'gap' })
  return out
})

const gapChars = computed(() => {
  const st = section.value?.stats
  if (!st) return 0
  return Math.max(0, st.total_chars - st.covered_chars)
})

const fmt = (v, d = 3) => (v === null || v === undefined ? '—' : Number(v).toFixed(d))
const isExpected = () => (props.expect ? props.expect.includes(props.hit.path) : false)

// ---- 正文里把命中词高亮 ----
// 必须自己转义：这里用 v-html 渲染，原文里可能有 < > &（Markdown 代码、箭头）。
const escapeHtml = (s) =>
  String(s).replace(
    /[&<>"']/g,
    (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' })[c],
  )

const escapeReg = (s) => s.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')

const expanded = ref(false)

const highlightedSnippet = computed(() => {
  // 卡片显示的是**命中的那一块**（`body` 已剥掉 heading_path 前缀），不是整节。
  const full = props.hit.body || props.hit.snippet || ''
  const text = expanded.value || full.length <= 320 ? full : full.slice(0, 320) + '…'
  // 命中词有两个来源：词面路的 `matched_terms`，以及向量路加权里的
  // `boosts.heading/body.matched`。纯向量模式没有词面路，只用前者会一片不亮。
  const boosts = props.hit.boosts || {}
  const terms = [
    ...new Set(
      [
        ...(props.hit.matched_terms || []),
        ...(boosts.body?.matched || []),
        ...(boosts.heading?.matched || []),
      ].filter(Boolean),
    ),
  ]
  if (!terms.length) return escapeHtml(text)

  // 长词优先，避免「任务」先吃掉「定时任务」这种嵌套匹配
  const sorted = terms.sort((a, b) => b.length - a.length)
  const re = new RegExp('(' + sorted.map(escapeReg).join('|') + ')', 'gi')
  const wanted = new Set(sorted.map((t) => t.toLowerCase()))

  // split 带捕获组：结果里"命中的片段"与"普通片段"交替出现
  return text
    .split(re)
    .map((part) =>
      wanted.has(part.toLowerCase())
        ? `<span class="hl">${escapeHtml(part)}</span>`
        : escapeHtml(part),
    )
    .join('')
})
</script>

<template>
  <div class="card">
    <div class="top">
      <span class="rank num">#{{ index }}</span>
      <span class="path">{{ hit.path }}</span>
      <span class="muted">› {{ hit.heading }}</span>
      <span v-if="isExpected()" class="ok">✓ 期望</span>
      <span class="score num">score {{ fmt(hit.score, 4) }}</span>
    </div>

    <div class="meta">
      <span>语义 {{ fmt(hit.vector_score) }}</span>
      <span>字面 {{ fmt(hit.lexical_score, 2) }}</span>
      <span>RRF {{ fmt(hit.rrf, 4) }}</span>
      <span v-for="s in hit.sources" :key="s" class="chip" :class="s">{{ sourceLabel(s) }}</span>
      <span v-if="hit.matched_terms?.length" class="terms">
        命中词 {{ hit.matched_terms.join('、') }}
      </span>
      <a href="#" @click.prevent="toggleRead">{{ open ? '收起整节' : '回读整节' }}</a>
    </div>

    <div class="snippet" v-html="highlightedSnippet"></div>
    <p v-if="!open" class="blknote muted">
      本块 {{ (hit.body || '').length }} 字
      <template v-if="(hit.body || '').length > 320">
        <a href="#" @click.prevent="expanded = !expanded">{{ expanded ? '收起本块' : '展开本块' }}</a>
      </template>
    </p>

    <div v-if="boostInfo" class="boosts">
      <div class="bline">
        <span class="blabel">{{ mode === 'vector' ? '分数构成' : '语义路得分' }}</span>
        <span class="bformula">
          {{ boostInfo.total.toFixed(4) }} =
          <template v-for="(p, i) in boostInfo.parts" :key="p.key">
            <span v-if="i" class="muted"> + </span>{{ p.key }} {{ p.value.toFixed(4) }}
          </template>
        </span>
        <span v-if="mode !== 'vector'" class="muted bnote">
          （这串分数决定它在语义榜的名次；上方的 score 是 RRF 融合分）
        </span>
      </div>
      <div class="bdetail">
        <span v-for="p in boostInfo.parts.slice(1)" :key="p.key" class="bitem">
          <b>{{ p.key }}</b>
          <span :class="p.value > 0 ? 'ok' : 'muted'">{{ p.detail }}</span>
        </span>
      </div>
    </div>

    <div v-if="open" class="section">
      <p v-if="loading" class="muted">读取中…</p>
      <p v-else-if="error" class="bad">读取失败：{{ error }}</p>
      <template v-else-if="section">
        <div class="sec-meta">
          <span>
            整节 · <b>{{ section.stats.blocks }}</b> 块 · 覆盖
            <b>{{ section.stats.covered_chars }}</b> / {{ section.stats.total_chars }} 字
          </span>
          <span v-if="gapChars" class="muted">
            缝隙 {{ gapChars }} 字（标题行 + 块间空行，块会 strip）
          </span>
          <span class="muted">行 {{ section.start_line }}–{{ section.end_line }}</span>
          <span class="hitmark">红底 = 命中的那块</span>
        </div>
        <pre class="sec-text"><template v-for="(seg, i) in segments" :key="i"
          ><span v-if="seg.matched" class="blk-tag">【本块 #{{ seg.no }}】</span
          ><span :class="seg.cls">{{ seg.text }}</span></template></pre>
      </template>
    </div>
  </div>
</template>

<style scoped>
.top {
  display: flex;
  gap: 10px;
  align-items: baseline;
  flex-wrap: wrap;
}
.rank {
  color: var(--dim);
}
.path {
  color: var(--accent);
  font-weight: 600;
}
.score {
  margin-left: auto;
  color: var(--dim);
  font-size: 12px;
}
.meta {
  color: var(--dim);
  font-size: 12px;
  margin-top: 6px;
  display: flex;
  gap: 14px;
  flex-wrap: wrap;
  align-items: center;
}
.meta a {
  color: var(--accent);
}
.terms {
  color: #ff5252;
  font-weight: 600;
  letter-spacing: 0.02em;
}
.snippet {
  color: #c2c7d0;
  margin-top: 6px;
  white-space: pre-wrap;
}
.blknote {
  font-size: 11px;
  margin: 4px 0 0;
}
/* ---- 整节按块渲染 ---- */
.section {
  margin-top: 8px;
}
.sec-meta {
  display: flex;
  gap: 14px;
  flex-wrap: wrap;
  font-size: 12px;
  color: var(--dim);
  margin-bottom: 6px;
}
.sec-meta b {
  color: var(--fg);
}
.hitmark {
  color: #ff5252;
}
.sec-text {
  max-height: 420px;
}
.sec-text .blk {
  background: rgba(88, 166, 255, 0.07);
  border-radius: 3px;
}
.sec-text .blk.hit {
  background: rgba(255, 82, 82, 0.16);
  outline: 1px solid rgba(255, 82, 82, 0.45);
}
.sec-text .gap {
  color: #5b6478;
}
.blk-tag {
  color: #ff5252;
  font-weight: 700;
}
/* v-html 渲染的内容不受 scoped 约束，用 :deep 才能命中 */
.snippet :deep(.hl) {
  color: #ff5252;
  background: rgba(255, 82, 82, 0.14);
  border-radius: 3px;
  padding: 0 2px;
  font-weight: 600;
}
.boosts {
  margin-top: 8px;
  padding-top: 7px;
  border-top: 1px dashed var(--line);
  font-size: 12px;
}
.bline {
  display: flex;
  gap: 8px;
  flex-wrap: wrap;
  align-items: baseline;
}
.blabel {
  color: var(--dim);
}
.bformula {
  font-variant-numeric: tabular-nums;
  color: #c2c7d0;
}
.bnote {
  font-size: 11px;
}
.bdetail {
  margin-top: 3px;
  display: flex;
  gap: 14px;
  flex-wrap: wrap;
  color: var(--dim);
}
.bitem b {
  color: #8b93a7;
  font-weight: 600;
  margin-right: 5px;
}
</style>
