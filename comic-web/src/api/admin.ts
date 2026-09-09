// 采集管理接口（运维控制台）—— 无需登录，本地演示
// 职责：列出数据源 / 开关采集 / 手动触发采集（增量|全量 + since/limit）/
//      手动触发懒转存（source/since/until/limit）/ 查询后台任务状态。
import type { AdminTask, SourceInfo } from '../types'
import { request } from './request'

/**
 * 列出所有数据源及运行状态（启用开关/库内数量/上次同步时间）
 * @see GET /api/admin/sources
 */
export function getAdminSources(): Promise<SourceInfo[]> {
  return request<SourceInfo[]>('/api/admin/sources')
}

/**
 * 切换某源采集开关（持久化到后端 source_state.json）
 * @param name 源站名
 * @returns 切换后的启用状态
 * @see POST /api/admin/sources/{name}/toggle
 */
export function toggleAdminSource(name: string): Promise<{ name: string; enabled: boolean }> {
  return request(`/api/admin/sources/${name}/toggle`, { method: 'POST' })
}

export interface AdminSyncRequest {
  source: string
  mode: 'incremental' | 'full'
  since?: string      // 起始日期（ISO），优先于上次同步水位
  limit?: number      // 本次最多收录漫画数
}

/**
 * 触发一次采集（后台线程执行，返回 taskId 供轮询）
 * @see POST /api/admin/sync
 */
export function startAdminSync(body: AdminSyncRequest): Promise<{ taskId: string }> {
  return request('/api/admin/sync', { method: 'POST', data: body })
}

export interface AdminTransferRequest {
  source?: string     // 仅转存某源；空 = 不限源
  since?: string
  until?: string
  limit?: number
}

/**
 * 触发一次懒转存（后台线程执行，返回 taskId 供轮询）
 * @see POST /api/admin/transfer
 */
export function startAdminTransfer(body: AdminTransferRequest): Promise<{ taskId: string }> {
  return request('/api/admin/transfer', { method: 'POST', data: body })
}

/**
 * 查询单个后台任务状态（触发后轮询到 done/failed）
 * @see GET /api/admin/tasks/{taskId}
 */
export function getAdminTask(taskId: string): Promise<AdminTask> {
  return request<AdminTask>(`/api/admin/tasks/${taskId}`)
}

/**
 * 查询最近的后台任务列表
 * @see GET /api/admin/tasks
 */
export function getAdminTasks(): Promise<AdminTask[]> {
  return request<AdminTask[]>('/api/admin/tasks')
}
