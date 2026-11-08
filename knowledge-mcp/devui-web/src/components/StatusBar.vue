<script setup>
import { onMounted, ref } from 'vue'
import { api } from '../api'

const info = ref(null)
const error = ref('')

const rebuilding = ref(false)
const notice = ref('')
const noticeKind = ref('ok')

async function load() {
  error.value = ''
  try {
    info.value = await api.status()
  } catch (e) {
    error.value = e.message
  }
}

async function rebuild() {
  if (rebuilding.value) return
  rebuilding.value = true
  notice.value = ''
  const started = Date.now()
  try {
    const r = await api.rebuild()
    if (r.ok) {
      const secs = ((Date.now() - started) / 1000).toFixed(1)
      noticeKind.value = 'ok'
      notice.value = `重建完成：${r.files} 文件 / ${r.chunks} chunk → ${r.collection}（${secs}s）`
      await load()
    } else {
      noticeKind.value = 'bad'
      notice.value = `重建失败：${r.error}`
    }
  } catch (e) {
    noticeKind.value = 'bad'
    notice.value = `重建失败：${e.message}`
  } finally {
    rebuilding.value = false
  }
}

onMounted(load)
defineExpose({ load })
</script>

<template>
  <div class="wrap">
    <div class="status">
      <span v-if="error" class="bad">状态读取失败：{{ error }}</span>
      <template v-else-if="info">
        <span>嵌入 <b>{{ info.embedding.backend }}/{{ info.embedding.model }}</b></span>
        <span>分词 <b>{{ info.tokenizer.backend }}</b></span>
        <span>语料 <b>{{ info.corpus_chunks }}</b> chunk</span>
        <span>已索引 <b>{{ info.indexed?.documents ?? '—' }}</b></span>
        <span>集合 <b>{{ info.collection }}</b></span>
        <span v-if="info.stale === true" class="mid">索引已过期</span>
        <span v-else-if="info.stale === false" class="ok">索引最新</span>
      </template>
      <span v-else class="muted">加载中…</span>
    </div>

    <div class="actions">
      <button class="ghost small" :disabled="rebuilding" @click="rebuild">
        {{ rebuilding ? '重建中…（约 40 秒）' : '重建索引' }}
      </button>
      <span v-if="notice" :class="noticeKind">{{ notice }}</span>
    </div>
  </div>
</template>

<style scoped>
.wrap {
  display: flex;
  gap: 16px;
  align-items: center;
  flex-wrap: wrap;
}
.status {
  color: var(--dim);
  font-size: 12px;
  display: flex;
  gap: 14px;
  flex-wrap: wrap;
}
.status b {
  color: var(--fg);
  font-weight: 600;
}
.actions {
  display: flex;
  gap: 10px;
  align-items: center;
  font-size: 12px;
}
.small {
  padding: 5px 12px;
  font-size: 12px;
}
</style>
