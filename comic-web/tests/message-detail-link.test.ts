// 消息中心的「详情链接」判定：`detailPath` 决定一条消息点了能不能跳、跳到哪个作品。
//
// 它只有一处真源（`stores/message.ts`），但**错一次就是全站跳错**：
//   - 放宽成「有 comicId 就跳」→ 将来别的类型带同名字段会被误连；
//   - 不收口非法值（`0` / `"abc"` / `null`）→ 跳到 `/comic/0` / `/comic/NaN` 白屏。
// 所以这里把边界钉死。注意 `params` 的 `comicId` 可能来自老消息或外部写者，写成字符串。
//
// 与 comic-front/tests/message-detail-link.test.ts 是**同一份矩阵**（两端各一份判定）——
// 改这里必须同步改那边。
import { describe, expect, it } from 'vitest'
import { detailPath } from '../src/stores/message'
import type { NoticeItem } from '../src/stores/message'

const BASE: NoticeItem = {
  id: 'msg-1',
  messageId: 1,
  kind: 'update',
  level: 'info',
  title: '《某作品》更新了',
  body: '新增 3 话',
  params: null,
  taskId: '',
  source: 'baozimh',
  username: '',
  minRole: '',
  status: 'done',
  time: null,
  read: false,
}

/** 造一条消息：只关心 kind 与 params，其余字段用基线补齐 */
function item(kind: string, params: unknown): NoticeItem {
  return { ...BASE, kind, params: params as Record<string, unknown> | null }
}

describe('detailPath —— 只有收藏更新（kind=update + 正整数 comicId）才是详情链接', () => {
  it('update + 正整数 comicId → /comic/<id>', () => {
    expect(detailPath(item('update', { comicId: 12 }))).toBe('/comic/12')
  })

  it('comicId 是字符串（老消息 / 外部写者）也认，归一成数字', () => {
    expect(detailPath(item('update', { comicId: '12' }))).toBe('/comic/12')
  })

  it('params 有多余键不影响判定', () => {
    expect(detailPath(item('update', { comicId: 12, newChapters: 3, source: 'baozimh' }))).toBe('/comic/12')
  })

  it('非法 comicId（0 / 负数 / 非数字 / null）→ 空串（退回只标已读）', () => {
    expect(detailPath(item('update', { comicId: 0 }))).toBe('')
    expect(detailPath(item('update', { comicId: -3 }))).toBe('')
    expect(detailPath(item('update', { comicId: 'abc' }))).toBe('')
    expect(detailPath(item('update', { comicId: null }))).toBe('')
    expect(detailPath(item('update', { comicId: 12.5 }))).toBe('')
  })

  it('params 缺失 / 空对象 / 非对象 → 空串，且不抛错', () => {
    expect(detailPath(item('update', null))).toBe('')
    expect(detailPath(item('update', {}))).toBe('')
    expect(detailPath(item('update', 'not-an-object'))).toBe('')
  })

  it('非 update 类型即使误带 comicId 也不跳（不允许隐式规则）', () => {
    expect(detailPath(item('sync', { comicId: 12 }))).toBe('')
    expect(detailPath(item('inspect', { comicId: 12 }))).toBe('')
    expect(detailPath(item('system', { comicId: 12 }))).toBe('')
  })
})
