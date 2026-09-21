// 采集管理接口（运维控制台）—— **需超级管理员**（role='admin'）
// 职责：列出数据源 / 开关采集 / 手动触发采集（增量|全量 + since/limit）/
//      手动触发失效巡检（source/since/until；含转存未转存页 + 全表校验恢复 + 全库封面自愈）/
//      手动触发按作品封面自愈（keyword 必填）/
//      查询后台任务状态 / 读取运行日志末尾 / 授权页：列用户 + 设置角色。
// 鉴权：后端在 router 上挂了 require_admin（超管或普通管理员）—— 未登录 401（拦截器跳登录页）、
//       权限不足 403。授权页那组接口门槛更高：仅超管（require_superadmin）。
// ⚠️ 独立的「触发转存」接口已删除（2026-09-21）：巡检第 1 步本就是 lazy_transfer，无独立价值。
import type {
  AdminTask,
  AdminUser,
  AdminUserPage,
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

export interface AdminInspectRequest {
  source?: string     // 仅巡检某源；空 = 不限源
  since?: string
  until?: string
}

/**
 * 触发一次失效巡检（后台线程执行，返回 taskId 供轮询）
 *
 * **全库维护的唯一入口**，三步：① 转存窗口内未转存页（内部即 `lazy_transfer`）；
 * ② **全表**校验已转存对象是否还在，缺失则恢复（按 id 键集分页遍历全表，不会截断）；
 * ③ 全库封面自愈（原挂在已删除的「触发转存」上，2026-09-21 并入这里）。
 * @see POST /api/admin/inspect
 */
export function startAdminInspect(body: AdminInspectRequest): Promise<{ taskId: string }> {
  return request('/api/admin/inspect', { method: 'POST', data: body })
}

export interface AdminHealCoversRequest {
  keyword: string     // 漫画名称或 ID，可多个（逗号/空格/换行分隔）—— **必填，不允许留空**
  source?: string     // 可再按源收窄；空 = 不限源
}

/**
 * 触发一次封面自愈（后台线程执行，返回 taskId 供轮询）
 *
 * **按作品**：填漫画名称或 ID（可多个），命中作品**强制回源重抓封面并覆盖** ——
 * 用于修「封面文件在、但内容是错的」（普通自愈只看文件在不在，永远修不到错图）。
 * @see POST /api/admin/heal-covers
 */
export function startAdminHealCovers(body: AdminHealCoversRequest): Promise<{ taskId: string }> {
  return request('/api/admin/heal-covers', { method: 'POST', data: body })
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

// ================= 授权页（给其他用户授权） =================
// ⚠️ 这一组接口**仅超级管理员**可用（后端挂的是 require_superadmin，不是 require_admin）：
// 普通管理员能进管理台与日志页，但进不了授权页、也调不通这两个接口（403）。

/**
 * 用户列表（授权页）
 * @param params keyword 匹配用户名/昵称；page/pageSize 分页
 * @returns AdminUserPage（items + total + page + pageSize）；role 为 superadmin/admin/user
 * @see GET /api/admin/users
 */
export function getAdminUsers(params: {
  keyword?: string
  page?: number
  pageSize?: number
} = {}): Promise<AdminUserPage> {
  return request<AdminUserPage>('/api/admin/users', { params })
}

/**
 * 设置用户角色（授权 / 取消授权）—— 只能在 **普通管理员 ⇄ 普通用户** 之间切
 * @param userId 目标用户 id
 * @param role 'admin'（普通管理员）/ 'user'（普通用户）
 * @returns 更新后的 { id, role }
 * @remarks 后端会拒绝：改自己、授予 superadmin、目标是超级管理员（400）
 * @see POST /api/admin/users/{userId}/role
 */
export function setUserRole(userId: number, role: string): Promise<{ id: number; role: string }> {
  return request(`/api/admin/users/${userId}/role`, { method: 'POST', data: { role } })
}
