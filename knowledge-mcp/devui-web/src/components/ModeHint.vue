<script setup>
import { computed } from 'vue'
import { MODE_BY_KEY } from '../modes'

const props = defineProps({
  mode: { type: String, required: true },
  // compact=true 只显示一行短说明（对比页的列头用）
  compact: { type: Boolean, default: false },
})

const info = computed(() => MODE_BY_KEY[props.mode] ?? null)
</script>

<template>
  <div v-if="info" class="hint" :class="{ compact }">
    <p class="short">
      <b>{{ info.label }}</b>
      <span class="muted">·</span>
      {{ info.short }}
    </p>

    <details v-if="!compact">
      <summary class="muted">展开看细节</summary>
      <div class="body">
        <p>{{ info.detail }}</p>
        <ul>
          <li><span class="ok">擅长</span>：{{ info.good }}</li>
          <li><span class="bad">不擅长</span>：{{ info.bad }}</li>
          <li><span class="mid">分数</span>：{{ info.score }}</li>
        </ul>
      </div>
    </details>
  </div>
</template>

<style scoped>
.hint {
  font-size: 12px;
  color: var(--dim);
  margin: 2px 0 10px;
}
.hint.compact {
  margin: 0 0 6px;
}
.short {
  margin: 0;
  color: var(--dim);
}
.short b {
  color: var(--fg);
  font-weight: 600;
}
details {
  margin-top: 4px;
}
summary {
  cursor: pointer;
  color: var(--accent);
  font-size: 12px;
}
.body {
  border-left: 2px solid var(--line);
  padding-left: 10px;
  margin-top: 6px;
}
.body p {
  margin: 0 0 6px;
  color: #c2c7d0;
}
.body ul {
  margin: 0;
  padding-left: 16px;
}
.body li {
  margin: 2px 0;
}
</style>
