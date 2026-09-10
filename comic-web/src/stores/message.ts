// 消息中心全局 store（Pinia）
//
// 设计目标：把「采集/转存」的任务结果从管理页内部的临时状态，升级为**全站可读的消息中心**，
// 顶栏在登录账号旁展示未读角标，点击展开消息面板；并预留「系统消息推送」入口（addSystem）。
//
// 关键点：
// - 轮询放在 store（单例）而非组件，任务即使离开 /admin 页也会继续跟踪到 done/failed；
// - 消息类型：sync(采集) / transfer(转存) / system(系统推送)；
// - 持久化：已完成消息落 localStorage（key=comic_msg_notices，上限 50 条），刷新不丢；
//   刷新时仍在 running 的消息视为「任务已中断」（后端任务无法跨会话恢复），标记为 failed；
// - toast 结果弹窗也由 store 持有，App 顶栏统一渲染，任何页面都能看到执行完毕提示。
import { computed, ref, watch } from 'vue'
import { defineStore } from 'pinia'
import { getAdminTask } from '../api'
import type { AdminTask } from '../types'

/** 消息类型：采集 / 懒转存 / 系统推送 */
export type NoticeKind = 'sync' | 'transfer' | 'system'
/** 消息状态：运行中 / 完成 / 失败 / 通知（系统消息） */
export type NoticeStatus = 'running' | 'done' | 'failed' | 'info'

export interface NoticeItem {
  id: string
  kind: NoticeKind
  status: NoticeStatus
  source?: string        // 数据源名（system 消息为空）
  mode?: string          // 采集模式：incremental / full
  summary: string        // 主文本（结果摘要）
  detail: string         // 次要文本（预留槽位，当前一律为空不渲染）
  time: string           // ISO 时间
  read: boolean          // 是否已读（未读计角标）
}

const STORAGE_KEY = 'comic_msg_notices'
const MAX_NOTICES = 50
const POLL_INTERVAL = 1500   // 轮询间隔（ms）
const TOAST_DURATION = 6000  // 结果弹窗停留（ms）

/** 任务结果摘要（采集：扫描/新增/更新/章节/失败；转存：检查/成功/失败） */
export function noticeSummary(t: AdminTask): string {
  if (t.status !== 'done' || !t.result) return ''
  if (t.type === 'sync') {
    const s = t.result.stats as Record<string, number> | undefined
    if (s) {
      return `扫描 ${s.total_seen} 部 | 新增 ${s.new_comics} | 更新 ${s.updated_comics} | 新增章节 ${s.new_chapters} | 失败 ${s.failed}`
    }
  }
  const r = t.result as Record<string, number>
  return `检查 ${r.checked ?? 0} | 成功 ${r.transferred ?? 0} | 失败 ${r.failed ?? 0}`
}

export const useMessageStore = defineStore('message', () => {
  const notices = ref<NoticeItem[]>([])
  const toast = ref<NoticeItem | null>(null)

  /** 未读数（运行中的任务不计未读） */
  const unread = computed(() => notices.value.filter((n) => !n.read && n.status !== 'running').length)

  // 持久化：仅落「已完成」消息，running 的刷新后无意义
  watch(
    notices,
    () => {
      try {
        const done = notices.value.filter((n) => n.status !== 'running').slice(0, MAX_NOTICES)
        localStorage.setItem(STORAGE_KEY, JSON.stringify(done))
      } catch {
        /* 存储不可用则忽略 */
      }
    },
    { deep: true },
  )

  /** 兼容历史消息：剔除摘要里已下线的「｜ 封面自愈 修复 X · 跳过 Y」片段 */
  function pruneLegacySummary(summary: string): string {
    if (!summary) return ''
    return summary.replace(/\s*｜\s*封面自愈[^｜]*/g, '').trim()
  }

  /** 启动：从 localStorage 载入历史；刷新前仍在 running 的标记为中断 */
  function init() {
    try {
      const raw = localStorage.getItem(STORAGE_KEY)
      if (!raw) return
      const items = JSON.parse(raw) as NoticeItem[]
      notices.value = items.map((n) => {
        if (n.status === 'running') {
          return { ...n, status: 'failed' as NoticeStatus, summary: '任务已中断', read: true, detail: '' }
        }
        // 次要文本已下线，历史消息里的旧 detail 一并清空
        return { ...n, summary: pruneLegacySummary(n.summary), detail: '' }
      })
    } catch {
      /* 解析失败则从空开始 */
    }
  }

  /** 轮询任务直到 done/failed，回填摘要并置为未读 + 弹 toast */
  function pollTask(taskId: string) {
    const step = async () => {
      try {
        const t = await getAdminTask(taskId)
        const item = notices.value.find((n) => n.id === taskId)
        if (!item) return
        if (t.status === 'running') {
          window.setTimeout(step, POLL_INTERVAL)
          return
        }
        item.status = t.status
        item.summary = t.status === 'failed' ? (t.message || '任务失败') : noticeSummary(t)
        item.read = false
        toast.value = item
        window.setTimeout(() => {
          if (toast.value && toast.value.id === taskId) toast.value = null
        }, TOAST_DURATION)
      } catch {
        // 查询失败：保留最后状态，不再重试
      }
    }
    step()
  }

  /** 触发任务后登记（占位 running，确保能检测到 running→结束 的跳变） */
  function trackTask(taskId: string, kind: 'sync' | 'transfer', source: string, mode?: string) {
    notices.value = notices.value.filter((n) => n.id !== taskId)
    notices.value.unshift({
      id: taskId,
      kind,
      status: 'running',
      source,
      mode,
      summary: kind === 'sync' ? '采集进行中…' : '转存进行中…',
      detail: '',
      time: new Date().toISOString(),
      read: true,
    })
    pollTask(taskId)
  }

  /** 系统消息推送入口（预留：后续接后端系统通知 / 运维广播） */
  function addSystem(text: string, detail = '') {
    notices.value.unshift({
      id: 'sys-' + Date.now() + '-' + Math.random().toString(36).slice(2, 7),
      kind: 'system',
      status: 'info',
      summary: text,
      detail,
      time: new Date().toISOString(),
      read: false,
    })
  }

  /** 全部标为已读（打开消息面板时调用） */
  function markAllRead() {
    notices.value.forEach((n) => (n.read = true))
  }

  function dismissToast() {
    toast.value = null
  }

  /** 清空全部消息 */
  function clear() {
    notices.value = []
    toast.value = null
  }

  return { notices, toast, unread, init, trackTask, addSystem, markAllRead, dismissToast, clear }
})
