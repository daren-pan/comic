// 「收藏有更新」角标的判定：`hasUpdate` / `buildReadAtMap`。
//
// 与 `comic-web/tests/favorite.test.ts` **同一组用例**（双端判定逻辑必须等价）。
//
// 这里钉的是三个最容易写错的点：
//   1) **等号** —— 更新时间与阅读时间相同不算「晚于」（相等 = 读到的最新版，不该亮）；
//   2) **时区** —— 两侧 ISO 可能一个带 `Z`、一个带 `+08:00`，字符串比较会误判；
//   3) **无基准** —— 没读过（`readAtMap` 查不到）或 `updatedAt` 为空一律不亮，
//      否则新收藏的书会全亮，角标等于失效。
import { describe, expect, it } from 'vitest'
import { buildReadAtMap, hasUpdate } from '../src/utils/favorite'

describe('hasUpdate —— updatedAt 晚于 readAt 才算「有更新」', () => {
  it('更新晚于阅读 → true', () => {
    const map = buildReadAtMap([{ comicId: 1, readAt: '2026-10-01T10:00:00Z' }])
    expect(hasUpdate({ id: 1, updatedAt: '2026-10-02T10:00:00Z' }, map)).toBe(true)
  })

  it('更新早于阅读 → false', () => {
    const map = buildReadAtMap([{ comicId: 1, readAt: '2026-10-02T10:00:00Z' }])
    expect(hasUpdate({ id: 1, updatedAt: '2026-10-01T10:00:00Z' }, map)).toBe(false)
  })

  it('更新时间与阅读时间相等 → false（读到的最新版不亮）', () => {
    const map = buildReadAtMap([{ comicId: 1, readAt: '2026-10-02T10:00:00Z' }])
    expect(hasUpdate({ id: 1, updatedAt: '2026-10-02T10:00:00Z' }, map)).toBe(false)
  })

  it('从未读过（无历史记录）→ false', () => {
    const map = buildReadAtMap([{ comicId: 2, readAt: '2026-10-01T10:00:00Z' }])
    expect(hasUpdate({ id: 1, updatedAt: '2026-10-09T10:00:00Z' }, map)).toBe(false)
    expect(hasUpdate({ id: 1, updatedAt: '2026-10-09T10:00:00Z' }, buildReadAtMap([]))).toBe(false)
  })

  it('updatedAt 为空 / 缺失 → false', () => {
    const map = buildReadAtMap([{ comicId: 1, readAt: '2026-10-01T10:00:00Z' }])
    expect(hasUpdate({ id: 1, updatedAt: '' }, map)).toBe(false)
    expect(hasUpdate({ id: 1, updatedAt: null }, map)).toBe(false)
    expect(hasUpdate({ id: 1 }, map)).toBe(false)
  })

  it('时区写法不同（Z vs +08:00）比较结果正确', () => {
    // 2026-10-02T08:00:00+08:00 = 2026-10-02T00:00:00Z，晚于 2026-10-01T23:00:00Z
    const map = buildReadAtMap([{ comicId: 1, readAt: '2026-10-01T23:00:00Z' }])
    expect(hasUpdate({ id: 1, updatedAt: '2026-10-02T08:00:00+08:00' }, map)).toBe(true)
    // 反过来：2026-10-01T06:00:00Z = 2026-10-01T14:00+08:00，早于 2026-10-01T23:00:00Z
    expect(hasUpdate({ id: 1, updatedAt: '2026-10-01T06:00:00Z' }, map)).toBe(false)
  })
})

describe('buildReadAtMap —— comicId → 最后一次阅读时间（毫秒）', () => {
  it('同一作品多条历史取最大 readAt', () => {
    const map = buildReadAtMap([
      { comicId: 1, readAt: '2026-10-01T10:00:00Z' },
      { comicId: 1, readAt: '2026-10-05T10:00:00Z' },
      { comicId: 1, readAt: '2026-10-03T10:00:00Z' },
      { comicId: 2, readAt: '2026-10-02T10:00:00Z' },
    ])
    expect(map.get(1)).toBe(Date.parse('2026-10-05T10:00:00Z'))
    expect(map.get(2)).toBe(Date.parse('2026-10-02T10:00:00Z'))
  })

  it('readAt 不可解析的条目跳过，合法条目照常入表', () => {
    const map = buildReadAtMap([
      { comicId: 1, readAt: '坏数据' },
      { comicId: 1, readAt: '2026-10-01T10:00:00Z' },
    ])
    expect(map.get(1)).toBe(Date.parse('2026-10-01T10:00:00Z'))
    expect(buildReadAtMap([]).size).toBe(0)
  })
})
