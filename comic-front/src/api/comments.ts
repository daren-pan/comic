// 评论区接口（漫画详情页底部）
//  ├─ GET  /api/comics/:id/comments   列表（**任何人可看**）+ 总数 + 该作品的评论开关状态
//  └─ POST /api/comics/:id/comments   发表（**需登录**；未登录 401、评论区关闭 403）
//
// ⚠️ `enabled=false` 时**列表接口照样返回 200**（列表空 + enabled false）——
// 详情页要能区分「还没有人评论」与「评论区已关闭」，所以关闭态不是错误。
// 删除评论是管理动作，走 `api/admin.ts`（`require_admin`）。
import type { CommentPage } from '../types'
import { request } from './request'

/** 每页条数（与后端 `services.comments.DEFAULT_PAGE_SIZE` 对齐） */
export const COMMENT_PAGE_SIZE = 20

/** 评论列表（最新在前）。 */
export function getComments(
  comicId: number,
  page = 1,
  pageSize = COMMENT_PAGE_SIZE,
): Promise<CommentPage> {
  return request<CommentPage>(`/api/comics/${comicId}/comments`, { params: { page, pageSize } })
}

/** 发表一条评论（需登录）。返回新评论 id —— 调用方据此**重拉第一页**（最新在前）。 */
export function addComment(comicId: number, content: string): Promise<{ id: number }> {
  return request<{ id: number }>(`/api/comics/${comicId}/comments`, {
    method: 'POST',
    data: { content },
  })
}
