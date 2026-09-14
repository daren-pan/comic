// 采集管理接口（运维控制台）—— 无需登录，本地演示
// 职责：列出数据源 / 开关采集 / 手动触发采集（增量|全量 + since/limit）/
//      手动触发懒转存（source/since/until/limit）/
//      手动触发失效巡检（source/since/until）/ 查询后台任务状态 / 读取运行日志末尾。
import type {
  AdminTask,
  LogOptions,
  LogQuery,
  LogQueryResult,
  LogRecord,
  SourceInfo,
} from '../types'
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

export interface AdminInspectRequest {
  source?: string     // 仅巡检某源；空 = 不限源
  since?: string
  until?: string
}

/**
 * 触发一次失效巡检（后台线程执行，返回 taskId 供轮询）
 *
 * 与「转存」的区别：转存只做「未转存 → 转存」；巡检在此基础上再多做一步
 * 「已转存对象校验 + 丢失恢复」（按 id 键集分页遍历全表，不会截断）。
 * @see POST /api/admin/inspect
 */
export function startAdminInspect(body: AdminInspectRequest): Promise<{ taskId: string }> {
  return request('/api/admin/inspect', { method: 'POST', data: body })
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

/**
 * 查询运行日志（`log_record` 表）—— 按级别 / 源站 / 事件 / 任务 / 作品 / 关键字 / 时间窗筛。
 * 日志由后端 logging Handler 在打日志时自动落库，所以内容与 `logs/api.log` 里的业务日志一致。
 * @see GET /api/admin/logs
 */
export function getLogRecords(params: LogQuery): Promise<LogQueryResult> {
  return request<LogQueryResult>('/api/admin/logs', { params })
}

/**
 * 单条日志详情（含异常堆栈全文；列表接口不带堆栈）
 * @see GET /api/admin/logs/{id}
 */
export function getLogDetail(id: number): Promise<LogRecord> {
  return request<LogRecord>(`/api/admin/logs/${id}`)
}

/**
 * 日志查询页的筛选候选值（级别 / 事件类型）
 * @see GET /api/admin/logs/options
 */
export function getLogOptions(): Promise<LogOptions> {
  return request<LogOptions>('/api/admin/logs/options')
}

/**
 * 删除 N 天前的日志（保留策略的手动入口；后端不做自动清理）
 * @see POST /api/admin/logs/purge
 */
export function purgeLogs(days: number): Promise<{ deleted: number }> {
  return request('/api/admin/logs/purge', { method: 'POST', params: { days } })
}
