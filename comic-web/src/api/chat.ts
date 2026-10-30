// 客服对话接口（右上角「客服」入口用）
//
// 与 `admin.ts` 里的 `/api/chat/lab/*` 是两套接口：
//   · lab   —— 管理员的实验接口，能调 topK / 阈值，返回调试用的 context
//   · ask   —— 面向普通用户，只收一个问题，返回答案 + 命中的资料标题
import { request } from './request'

/** 一轮对话（后端据此判断要不要把追问改写成独立问题） */
export interface ChatTurn {
  role: 'user' | 'bot'
  content: string
}

/** 答案引用了哪条资料（只给标题，不给正文和分数） */
export interface ChatHit {
  title: string
  kind: string
}

export interface ChatAnswer {
  answer: string
  hits: ChatHit[]
  /** 追问被改写成的独立问题；没改写时为 null */
  rewritten: string | null
  model: string
}

/**
 * 向客服提问。
 *
 * ⚠️ **当前仅管理员可调**（后端 `require_admin`，普通用户 403）。
 * 限额：60 条/小时/账号（超了后端返 429）。
 * @param question 用户问题（1~200 字）
 * @param history  最近的对话（最多 12 条；后端还会再截一次，防绕过）
 * @see POST /api/chat/ask
 */
export function askChat(question: string, history: ChatTurn[] = []): Promise<ChatAnswer> {
  return request<ChatAnswer>('/api/chat/ask', {
    method: 'POST',
    data: { question, history },
  })
}
