// 消息中心接口（`/api/messages`）
//
// 消息是**平台级**的：api 的任务收尾、独立进程 `comic-scheduler`、将来的外部系统都往这里发。
// 前端只读（列表自动带未读数）；「全部已读」在这里落库（已读是**全局一份**，换机器也在）。
//
// ⚠️ 列表里会出现两种条目：库里已发生的消息（`id = msg-<数字>`，`messageId` 有值）与
// **正在跑的任务**（`id = 任务号`，`messageId = null`）——后者还没"发生完"，由后端临时并入。
import { request } from './request'
import type { MessageFeed } from '../types'

/**
 * 消息列表 + 未读数（一次请求两样都拿到，轮询只打一个接口）
 *
 * @param limit       最多返回多少条（默认 50）
 * @param unreadOnly  只看未读（此时不包含"正在跑的任务" —— 它们不算未读）
 * @see GET /api/messages
 */
export function getMessages(params?: { limit?: number; unreadOnly?: boolean }): Promise<MessageFeed> {
  const parts: string[] = []
  if (params?.limit) parts.push(`limit=${params.limit}`)
  if (params?.unreadOnly) parts.push('unread_only=true')
  return request<MessageFeed>(`/api/messages${parts.length ? `?${parts.join('&')}` : ''}`)
}

/**
 * 未读数（只给角标用；列表接口本来也会带回来）
 * @see GET /api/messages/unread
 */
export function getUnreadCount(): Promise<{ unread: number }> {
  return request<{ unread: number }>('/api/messages/unread')
}

/**
 * 标记一条已读
 * @param messageId 列表里的 `messageId`（数字；"正在跑的任务"条目没有它）
 * @see POST /api/messages/{id}/read
 */
export function markMessageRead(messageId: number): Promise<{ changed: number }> {
  return request<{ changed: number }>(`/api/messages/${messageId}/read`, { method: 'POST' })
}

/**
 * 全部标为已读（**全局一份**：单/双管理员语义，见 mysql_schema.sql）
 * @see POST /api/messages/read-all
 */
export function markAllMessagesRead(): Promise<{ changed: number }> {
  return request<{ changed: number }>('/api/messages/read-all', { method: 'POST' })
}
