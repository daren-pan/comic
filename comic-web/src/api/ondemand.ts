// 源站搜索与按需导入（搜索页「其他来源」用）—— **搜索只读，导入才写库**
// 流程：站内搜不到 → 搜源站 → 用户点「导入并阅读」→ 轮询任务 → 跳详情页。
import type { AdminTask, ImportResult, SourceSearchGroup } from '../types'
import { getAdminTask } from './admin'
import { request } from './request'

/**
 * 搜索**源站**（只读，不写库）—— 站内搜不到时去「其他来源」找。
 * 返回按源分组的结果；只含支持搜索的源，单源失败会被后端静默跳过。
 * @see GET /api/sources/search
 */
export function searchSources(q: string, source?: string, limit = 20): Promise<SourceSearchGroup[]> {
  const params: Record<string, string | number> = { q, limit }
  if (source) params.source = source
  return request<SourceSearchGroup[]>('/api/sources/search', { params })
}

export interface ImportRequest {
  source: string
  keyword?: string         // 按书名导入（源站搜索后取第一条）
  ref?: string             // 按作品链接 / 作品 ID 导入
  sourceComicId?: string   // 直接指定源站作品 ID（最精确）
  firstChapters?: number   // 留空 = 全量收目录
}

/**
 * 触发按需导入（后台线程执行，返回 taskId 供轮询）
 * 导入只写书目 + 全量章节 + 封面，**不下载正文图**：图片在阅读时按需取回。
 * @see POST /api/admin/import
 */
export function startImport(body: ImportRequest): Promise<{ taskId: string }> {
  return request<{ taskId: string }>('/api/admin/import', {
    method: 'POST',
    data: {
      source: body.source,
      keyword: body.keyword,
      ref: body.ref,
      source_comic_id: body.sourceComicId,
      first_chapters: body.firstChapters,
    },
  })
}

/**
 * 轮询导入任务直到结束；失败时抛出后端给出的原因（如「该作品在源站不可读」）。
 * 导入通常 1~3 秒完成（只请求一次详情），因此这里同步等待即可，不占消息中心。
 */
export async function waitImport(
  taskId: string,
  intervalMs = 700,
  timeoutMs = 60_000,
): Promise<AdminTask> {
  const deadline = Date.now() + timeoutMs
  for (;;) {
    const task = await getAdminTask(taskId)
    if (task.status !== 'running') {
      if (task.status === 'failed') throw new Error(task.message || '导入失败')
      return task
    }
    if (Date.now() > deadline) throw new Error('导入超时，请稍后在管理台任务列表查看')
    await new Promise((r) => setTimeout(r, intervalMs))
  }
}

/**
 * 一步完成「导入并阅读」：触发 → 轮询 → 返回结果（前端据此跳详情页）
 */
export async function importAndWait(body: ImportRequest): Promise<ImportResult> {
  const { taskId } = await startImport(body)
  const task = await waitImport(taskId)
  return task.result as unknown as ImportResult
}
