<!--
  在线客服：右侧悬浮球 + 对话抽屉

  ## 为什么整个组件 Teleport 到 body

  入口是 `position: fixed` 的悬浮球。如果它待在顶栏 `.nav` 里，会被 `.nav` 的
  `z-index: 100` 层叠上下文困住 —— 子元素 z-index 再大也压不过 `.nav` 之外的底栏
  （z-index: 120，见 Layout.vue 的说明）。挪到 body 下就没有这层限制了。

  ## 为什么消息只存在前端

  后端 `/api/chat/ask` 是**单轮**的：每次提问独立检索、独立回答，不读上文。
  所以 messages 仅用于展示，刷新即丢 —— 不是 bug，是当前实现如此。
  要做多轮，需要把历史一并传进 prompt（见 services/chat/lab/chain.py 的注释）。
-->
<script setup lang="ts">
import { computed, nextTick, ref } from 'vue'
import { askChat, type ChatHit } from '../api/chat'

interface Msg {
  role: 'user' | 'bot'
  text: string
  hits?: ChatHit[]
}

const open = ref(false)
const draft = ref('')
const loading = ref(false)
const messages = ref<Msg[]>([])
const listEl = ref<HTMLElement | null>(null)

const GREETING = '你好，我是小聚 🧭\n站内功能、找漫画、账号问题都可以问我。'
const QUICK = ['怎么收藏漫画', '图片加载不出来怎么办', '忘记密码了怎么办']

const canSend = computed(() => !loading.value && draft.value.trim().length > 0)

function toggle() {
  open.value = !open.value
  if (open.value) {
    if (!messages.value.length) {
      messages.value.push({ role: 'bot', text: GREETING })
    }
    scrollToBottom()
  }
}

function scrollToBottom() {
  nextTick(() => {
    const el = listEl.value
    if (el) el.scrollTop = el.scrollHeight
  })
}

async function send(text?: string) {
  const q = (text ?? draft.value).trim()
  if (!q || loading.value) return

  draft.value = ''
  messages.value.push({ role: 'user', text: q })
  scrollToBottom()

  loading.value = true
  try {
    const res = await askChat(q)
    messages.value.push({ role: 'bot', text: res.answer, hits: res.hits })
  } catch (e) {
    // request.ts 已经把后端的中文提示取出来了（429 限流 / 503 客服未配置…）
    messages.value.push({
      role: 'bot',
      text: (e as Error).message || '客服暂时不可用，请稍后再试',
    })
  } finally {
    loading.value = false
    scrollToBottom()
  }
}
</script>

<template>
  <Teleport to="body">
    <!-- 打开时整个隐藏：它 z-index 比面板高，留着会浮在对话区中间挡住文字。
         关闭走头部那个 ×，或用遮罩点空白处。 -->
    <button
      v-if="!open"
      class="chat-fab"
      type="button"
      title="在线客服"
      @click="toggle"
    >
      <span class="chat-fab-icon">💬</span>
      <span class="chat-fab-pulse"></span>
    </button>

    <div v-if="open" class="chat-mask" @click="open = false"></div>

    <section v-if="open" class="chat-panel" aria-label="在线客服">
      <header class="chat-head">
        <div class="chat-head-avatar">🧭</div>
        <div class="chat-head-info">
          <div class="chat-head-name">小聚</div>
          <div class="chat-head-state">
            <span class="chat-dot-green"></span>
            在线 · 基于站内资料回答
          </div>
        </div>
        <button class="chat-head-close" type="button" aria-label="关闭" @click="open = false">×</button>
      </header>

      <div ref="listEl" class="chat-list">
        <div v-for="(m, i) in messages" :key="i" class="chat-row" :class="m.role">
          <div v-if="m.role === 'bot'" class="chat-avatar">🧭</div>
          <div class="chat-col">
            <div class="chat-bubble">{{ m.text }}</div>
            <div v-if="m.hits && m.hits.length" class="chat-refs">
              <span class="chat-refs-label">参考</span>
              <span v-for="(h, j) in m.hits" :key="j" class="chat-ref">{{ h.title }}</span>
            </div>
          </div>
        </div>

        <div v-if="loading" class="chat-row bot">
          <div class="chat-avatar">🧭</div>
          <div class="chat-bubble chat-typing">
            <span class="chat-typing-dot"></span>
            <span class="chat-typing-dot"></span>
            <span class="chat-typing-dot"></span>
          </div>
        </div>

        <div v-if="messages.length <= 1 && !loading" class="chat-quick">
          <button
            v-for="q in QUICK"
            :key="q"
            class="chat-chip"
            type="button"
            @click="send(q)"
          >{{ q }}</button>
        </div>
      </div>

      <form class="chat-input" @submit.prevent="send()">
        <input
          v-model="draft"
          class="chat-field"
          type="text"
          maxlength="200"
          placeholder="问我点什么…"
          :disabled="loading"
        />
        <button class="chat-send" type="submit" :disabled="!canSend" aria-label="发送">↑</button>
      </form>
    </section>
  </Teleport>
</template>

<style scoped>
/* ---------- 悬浮球 ---------- */
.chat-fab {
  position: fixed;
  right: 26px;
  top: 50%;
  transform: translateY(-50%);
  z-index: 902;
  width: 56px;
  height: 56px;
  display: flex;
  align-items: center;
  justify-content: center;
  border: none;
  border-radius: 50%;
  background: var(--primary);
  color: #fff;
  font-size: 24px;
  line-height: 1;
  cursor: pointer;
  box-shadow: 0 6px 20px rgba(255, 90, 54, 0.35);
  transition: transform 0.18s ease, box-shadow 0.18s ease, background 0.18s ease;
}
.chat-fab:hover {
  transform: translateY(-50%) scale(1.06);
  box-shadow: 0 10px 26px rgba(255, 90, 54, 0.45);
}
.chat-fab-icon {
  position: relative;
  z-index: 1;
}
/* 呼吸光圈：提示「这儿能点」，不喧宾夺主 */
.chat-fab-pulse {
  position: absolute;
  inset: 0;
  border-radius: 50%;
  background: var(--primary);
  animation: chatPulse 2.4s ease-out infinite;
}
@keyframes chatPulse {
  0% { transform: scale(1); opacity: 0.55; }
  70% { transform: scale(1.55); opacity: 0; }
  100% { transform: scale(1.55); opacity: 0; }
}

/* ---------- 抽屉 ---------- */
.chat-mask {
  position: fixed;
  inset: 0;
  z-index: 900;
  background: rgba(30, 20, 12, 0.38);
  animation: chatFadeIn 0.18s ease-out;
}
@keyframes chatFadeIn {
  from { opacity: 0; }
  to { opacity: 1; }
}

.chat-panel {
  position: fixed;
  top: 0;
  right: 0;
  bottom: 0;
  z-index: 901;
  display: flex;
  flex-direction: column;
  width: 400px;
  max-width: 100vw;
  background: var(--bg);
  box-shadow: -12px 0 40px rgba(40, 25, 15, 0.18);
  animation: chatSlideIn 0.22s cubic-bezier(0.22, 0.61, 0.36, 1);
}
@keyframes chatSlideIn {
  from { transform: translateX(32px); opacity: 0; }
  to { transform: translateX(0); opacity: 1; }
}

/* ---------- 头部 ---------- */
.chat-head {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 15px 16px;
  background: var(--primary);
  color: #fff;
}
.chat-head-avatar {
  width: 38px;
  height: 38px;
  flex-shrink: 0;
  display: flex;
  align-items: center;
  justify-content: center;
  border-radius: 50%;
  background: rgba(255, 255, 255, 0.22);
  font-size: 19px;
}
.chat-head-info {
  flex: 1;
  min-width: 0;
}
.chat-head-name {
  font-size: 15px;
  font-weight: 500;
  line-height: 1.3;
}
.chat-head-state {
  display: flex;
  align-items: center;
  gap: 5px;
  margin-top: 2px;
  font-size: 12px;
  opacity: 0.9;
}
.chat-dot-green {
  width: 6px;
  height: 6px;
  border-radius: 50%;
  background: #4ade80;
  box-shadow: 0 0 0 2px rgba(74, 222, 128, 0.28);
}
.chat-head-close {
  width: 30px;
  height: 30px;
  flex-shrink: 0;
  border: none;
  border-radius: 50%;
  background: rgba(255, 255, 255, 0.16);
  color: #fff;
  font-size: 20px;
  line-height: 1;
  cursor: pointer;
  transition: background 0.15s;
}
.chat-head-close:hover {
  background: rgba(255, 255, 255, 0.3);
}

/* ---------- 消息区 ---------- */
.chat-list {
  flex: 1;
  overflow-y: auto;
  padding: 18px 16px 8px;
  display: flex;
  flex-direction: column;
  gap: 14px;
}
.chat-row {
  display: flex;
  gap: 8px;
  align-items: flex-start;
  animation: chatMsgIn 0.2s ease-out;
}
@keyframes chatMsgIn {
  from { opacity: 0; transform: translateY(6px); }
  to { opacity: 1; transform: translateY(0); }
}
.chat-row.user {
  flex-direction: row-reverse;
}
.chat-avatar {
  width: 30px;
  height: 30px;
  flex-shrink: 0;
  display: flex;
  align-items: center;
  justify-content: center;
  border-radius: 50%;
  background: var(--primary-soft);
  font-size: 15px;
}
.chat-col {
  max-width: 78%;
  display: flex;
  flex-direction: column;
  gap: 5px;
}
.chat-row.user .chat-col {
  align-items: flex-end;
}
.chat-bubble {
  padding: 10px 14px;
  border-radius: 14px;
  font-size: 14px;
  line-height: 1.7;
  white-space: pre-wrap;
  word-break: break-word;
}
.chat-row.bot .chat-bubble {
  background: var(--card);
  color: var(--text);
  border: 1px solid var(--border);
  border-top-left-radius: 4px;
  box-shadow: 0 1px 3px rgba(60, 40, 20, 0.05);
}
.chat-row.user .chat-bubble {
  background: var(--primary);
  color: #fff;
  border-top-right-radius: 4px;
}

.chat-refs {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 5px;
  padding: 0 2px;
  font-size: 11px;
  color: var(--text-2);
}
.chat-refs-label {
  opacity: 0.7;
}
.chat-ref {
  padding: 1px 7px;
  border-radius: 8px;
  background: var(--mute);
  color: var(--text-2);
}

/* 打字指示器：三点依次跳，比一句「正在输入…」更像在思考 */
.chat-typing {
  display: flex;
  align-items: center;
  gap: 5px;
  padding: 14px;
}
.chat-typing-dot {
  width: 6px;
  height: 6px;
  border-radius: 50%;
  background: var(--text-2);
  animation: chatBlink 1.2s infinite ease-in-out;
}
.chat-typing-dot:nth-child(2) { animation-delay: 0.18s; }
.chat-typing-dot:nth-child(3) { animation-delay: 0.36s; }
@keyframes chatBlink {
  0%, 60%, 100% { opacity: 0.28; transform: translateY(0); }
  30% { opacity: 1; transform: translateY(-3px); }
}

/* 快捷问题：竖排一列（横排时「图片加载不出来怎么办」这种长句子会把布局撑乱），
   左缩进 38px 与头像对齐。 */
.chat-quick {
  display: flex;
  flex-direction: column;
  gap: 8px;
  padding-left: 38px;
}
.chat-chip {
  padding: 9px 14px;
  border: 1px solid var(--border);
  border-radius: 12px;
  background: var(--card);
  color: var(--text-2);
  font-size: 13px;
  text-align: left;
  cursor: pointer;
  transition: border-color 0.15s, color 0.15s, background 0.15s;
}
.chat-chip:hover {
  border-color: var(--primary);
  color: var(--primary);
  background: var(--primary-soft);
}

/* ---------- 输入区 ---------- */
.chat-input {
  display: flex;
  gap: 8px;
  padding: 12px 14px calc(12px + env(safe-area-inset-bottom, 0px));
  background: var(--card);
  border-top: 1px solid var(--border);
}
.chat-field {
  flex: 1;
  min-width: 0;
  height: 40px;
  padding: 0 16px;
  border: 1px solid var(--border);
  border-radius: 20px;
  background: var(--surface-2);
  color: var(--text);
  font-size: 14px;
  outline: none;
  transition: border-color 0.15s, background 0.15s;
}
.chat-field:focus {
  border-color: var(--primary);
  background: var(--card);
}
.chat-field::placeholder {
  color: var(--text-2);
  opacity: 0.7;
}
.chat-send {
  width: 40px;
  height: 40px;
  flex-shrink: 0;
  border: none;
  border-radius: 50%;
  background: var(--primary);
  color: #fff;
  font-size: 17px;
  line-height: 1;
  cursor: pointer;
  transition: background 0.15s, transform 0.15s;
}
.chat-send:hover:not(:disabled) {
  background: var(--primary-dark);
  transform: scale(1.05);
}
.chat-send:disabled {
  opacity: 0.4;
  cursor: default;
}

/* ---------- 窄屏 ---------- */
@media (max-width: 860px) {
  .chat-fab {
    top: auto;
    bottom: 88px;      /* 让开底栏（bottom-nav 高约 60px） */
    right: 16px;
    width: 52px;
    height: 52px;
    transform: none;
    font-size: 22px;
  }
  .chat-fab:hover {
    transform: scale(1.06);
  }
  .chat-panel {
    width: 100%;
  }
  .chat-col {
    max-width: 82%;
  }
}
</style>
