// 消息中心全局 store（Pinia）—— **服务端通知中心（`message` 表）的视图**
//
// ⚠️ 这一块前后改了三版，都是往"更靠服务端、受众更广"走：
//   1.0 纯前端本地消息（点过哪个任务就登记一条、落 localStorage）→ 换机器就没了、定时轮次不出现；
//   2.0 直接读管理台任务表 → 定时轮次有了，但消息仍只等于"任务"，只有管理员有；
//   3.0（现在）**面向所有登录用户的通知中心**：`message` 表 + `POST /api/messages` 写入接口 ——
//       每条消息带**收件范围**（定向某人 / 最低角色），读取时由服务端按当前账号过滤，
//       **已读按账号各一份**（`message_read` 表：广播消息 A 读过不会清掉 B 的角标）。
//
// 本 store 只做三件事：拉 `GET /api/messages`（列表 + 未读数一次拿回）、标记已读、把"结果刚出来"
// 那一刻弹成 toast。**不存任何消息内容到本地** —— 换台机器打开，看到的是同一份。
//
// 关键点：
// - 列表里两种条目：库里的消息（`msg-<id>`）与**正在跑的任务**（任务号，后端临时并入，**仅管理员**）——
//   后者让"定时轮次正在跑"也能看见；跑完它会被那条正式消息取代（id 不同，不会重复）；
// - **轮询**：有 running 条目时 5s 一次（能看到 running → done 的跳变并弹 toast），空闲 60s 一次；
// - **登录即用**：数据源只要登录（内容按账号过滤），所以 Layout 按 `isLoggedIn` 拉起/停止轮询；
// - 唯一的本地提示是 `notify()`（权限门卫这类"被拦下"的即时提示）：只弹 toast、不进列表，
//   免得列表出现"换机器就没了"的第二类条目。
import { computed, ref } from 'vue'
import { defineStore } from 'pinia'
import { getMessages, markAllMessagesRead, markMessageRead } from '../api'
import type { MessageItem } from '../types'

/** 消息条目（= 接口出参形状；列表与 toast 共用同一份） */
export type NoticeItem = MessageItem
/** 消息状态（从 `status`/`level` 归一出来，供展示层用） */
export type NoticeStatus = 'running' | 'done' | 'failed' | 'info'

const LIMIT = 50             // 一次拉多少条
const POLL_RUNNING = 5000    // 有任务在跑时的轮询间隔（ms）
const POLL_IDLE = 60000      // 空闲时的轮询间隔（ms）
const TOAST_DURATION = 6000  // 结果弹窗停留（ms）

// ---- 展示用格式化（消息页与 toast **共用同一份**，不各写一份）----
/** 消息类型中文名 */
export function kindLabel(k: string): string {
  return (
    {
      sync: '采集',
      transfer: '转存',
      inspect: '巡检',
      heal: '自愈',
      import: '导入',
      schedule: '定时',
      system: '系统',
    } as Record<string, string>
  )[k] || '消息'
}
/** 消息状态中文名（运行中 / 完成 / 失败 / 通知）—— 由 `status` + `level` 归一 */
export function statusLabel(n: NoticeItem): string {
  if (n.status === 'running') return '运行中'
  if (n.status === 'failed' || n.level === 'error') return '失败'
  if (n.level === 'warn') return '警告'
  return n.kind === 'system' ? '通知' : '完成'
}
/** 消息时间：`MM-DD HH:mm` */
export function fmtMsgTime(iso: string | null): string {
  if (!iso) return '—'
  const d = new Date(iso)
  const pad = (n: number) => String(n).padStart(2, '0')
  return `${pad(d.getMonth() + 1)}-${pad(d.getDate())} ${pad(d.getHours())}:${pad(d.getMinutes())}`
}

/**
 * **入参一行**：这条消息对应哪段时间范围、当时是怎么点的（只列有的项；**没有入参返回空串**）。
 *
 * ⚠️ 没有 `params` 就**什么都不显示**，别去猜"起始 按源水位" ——
 * 那对"入参列上线之前产生的老消息"、以及不带入参的其他模块消息都是**编的**。
 *
 * 重点是**起始时间** `since`：
 * - 有值 → `起始 2026-10-01`（就是那轮采集/巡检的时间窗下界）；
 * - 为空时**两种语义不同**，别混着写：采集 = **按源自身水位**、巡检 = **不限**（全量校验）。
 *
 * 其余项（截止 / 增量全量 / 上限 / 关键字 / 前 N 话）也顺手带上 —— 复盘"当时点的是什么"。
 * 源名不在这里重复（列表已有独立的"源："那行）。
 */
export function paramSummary(n: NoticeItem): string {
  const p = n.params
  if (!p || typeof p !== 'object' || !Object.keys(p).length) return ''
  const obj = p as Record<string, unknown>
  const action = String(obj.action || '')
  const isInspect = n.kind === 'inspect' || action === 'inspect'
  const hasWindow = n.kind === 'sync' || n.kind === 'inspect' || n.kind === 'schedule'
  const since = obj.since ? String(obj.since).slice(0, 10) : ''
  const until = obj.until ? String(obj.until).slice(0, 10) : ''

  const parts: string[] = []
  if (hasWindow) {
    parts.push(since ? `起始 ${since}` : isInspect ? '起始 不限' : '起始 按源水位')
  }
  if (until) parts.push(`截止 ${until}`)
  if (obj.mode) parts.push(obj.mode === 'full' ? '全量' : '增量')
  if (obj.limit) parts.push(`上限 ${obj.limit}`)
  if (obj.keyword) parts.push(`关键字 ${String(obj.keyword).slice(0, 16)}`)
  if (obj.firstChapters) parts.push(`前 ${obj.firstChapters} 话`)
  return parts.join(' · ')
}

export const useMessageStore = defineStore('message', () => {
  const notices = ref<NoticeItem[]>([])
  const unread = ref(0)
  const toast = ref<NoticeItem | null>(null)
  const loading = ref(false)
  const error = ref('')

  let timer: ReturnType<typeof setTimeout> | null = null
  let started = false                       // 轮询循环是否已拉起（多处调 start 也只跑一个）
  let inflight = false                      // 防重入：上一轮还没回来就跳过这次
  // 见过"在跑"的任务：key 用 **taskId**（不是条目 id）——
  // 同一次任务在跑的时候 id 是任务号、跑完那条消息的 id 是 `msg-<n>`，**两个 id 不同**；
  // 只有按 taskId 才能把"跑完了"认出来，从而推送（弹结果提示）。任务号为空的条目才退回用 id。
  const runningSeen = new Set<string>()

  const hasRunning = computed(() => notices.value.some((n) => n.status === 'running'))

  /** 结束跳变 → 推送一次结果提示（无论这一轮是**谁**触发的：本机、别的机器、还是定时器） */
  function detectFinished(list: NoticeItem[]) {
    for (const n of list) {
      const key = n.taskId || n.id
      if (n.status === 'running') {
        runningSeen.add(key)
      } else if (runningSeen.has(key)) {
        runningSeen.delete(key)
        toast.value = n
        setTimeout(() => {
          if (toast.value && toast.value.id === n.id) toast.value = null
        }, TOAST_DURATION)
      }
    }
  }

  /** 拉一次消息（内容与未读数都来自服务端，本地不存） */
  async function refresh() {
    if (inflight) return
    inflight = true
    loading.value = notices.value.length === 0
    try {
      const feed = await getMessages({ limit: LIMIT })
      notices.value = feed.items || []
      unread.value = feed.unread || 0
      detectFinished(notices.value)
      error.value = ''
    } catch (e) {
      // 拉不到就保留上一次的结果（别清空成"暂无消息"，那会让人以为消息丢了）
      error.value = (e as Error).message || '加载消息失败'
    } finally {
      inflight = false
      loading.value = false
    }
  }

  /** 自调度轮询：有任务在跑就 5s 一次，空闲 60s 一次 */
  function schedule() {
    if (!started) return
    timer = setTimeout(async () => {
      await refresh()
      schedule()
    }, hasRunning.value ? POLL_RUNNING : POLL_IDLE)
  }

  /** 开始（幂等）：立刻拉一次并转入轮询。
   *
   *  由 Layout.vue 按 `isAdmin` 拉起 —— 数据源是管理台接口，普通用户既没有消息也不该打请求。
   */
  function start() {
    if (started) return
    started = true
    refresh()
    schedule()
  }

  /** 停止轮询（登出 / 被降权） */
  function stop() {
    started = false
    if (timer) {
      clearTimeout(timer)
      timer = null
    }
  }

  /** 全部标为已读（**落库**：换机器也还是已读） */
  async function markAllRead() {
    if (unread.value > 0) {
      try {
        await markAllMessagesRead()
      } catch {
        /* 标失败就保持未读，下次进页再试 */
      }
    }
    notices.value.forEach((n) => (n.read = true))
    unread.value = 0
  }

  /** 标记单条已读（点开某条时用；列表刷新后以服务端的 `read` 为准） */
  async function markRead(item: NoticeItem) {
    if (item.read || item.messageId === null) return
    try {
      await markMessageRead(item.messageId)
      item.read = true
      unread.value = Math.max(0, unread.value - 1)
    } catch {
      /* 忽略：下次刷新以服务端为准 */
    }
  }

  /** 本地即时提示（**唯一不进列表的消息**：权限门卫这类"被拦下"的提示）—— 只弹 toast */
  function notify(text: string, detail = '') {
    toast.value = {
      id: 'local-' + Date.now(),
      messageId: null,
      kind: 'system',
      level: 'warn',
      title: text,
      body: detail,
      taskId: '',
      source: '',
      username: '',
      status: 'done',
      time: null,
      read: true,
    }
    setTimeout(() => {
      if (toast.value && toast.value.id.startsWith('local-')) toast.value = null
    }, TOAST_DURATION)
  }

  function dismissToast() {
    toast.value = null
  }

  return {
    notices, unread, toast, loading, error,
    start, stop, refresh, markAllRead, markRead, notify, dismissToast,
  }
})
