// 收藏「有更新」判定 —— 纯函数，无副作用，便于单测。
//
// 口径：`Comic.updatedAt`（后端即 `comic.sync_time`）**晚于**该作品最后一次阅读时间
// （`HistoryEntry.readAt`）才算「有更新」。两侧都用 `Date.parse()` 转毫秒再比 ——
// 两者虽同为 ISO 8601，但时区写法可能不同（`Z` / `+08:00`），字符串比较会误判。
//
// ⚠️ 语义是「你上次读这本之后作品有过更新」，**不是**「有未读章节」：
//   - 从没读过的收藏没有基准时间 → 不亮（`readAtMap` 里查不到）；
//   - 读到最后一章后作品再更一次 → 才亮。
//
// ⚠️ 与 `comic-front/src/utils/favorite.ts` **保持一致**（双端等价，改一处要同步另一处）。

/** 历史记录里参与判定的字段 */
interface HistoryLike {
  comicId: number
  readAt: string
}

/** 收藏里参与判定的字段 */
interface ComicLike {
  id: number
  updatedAt?: string | null
}

/**
 * 把历史列表压成「本作品最后一次阅读时间」索引：`comicId -> readAt(ms)`。
 *
 * 同一作品可能有多条历史（读过不同章节），取**最大**的 `readAt`；
 * `readAt` 不可解析的条目跳过（坏数据不该让整页判定失效）。
 */
export function buildReadAtMap(history: HistoryLike[]): Map<number, number> {
  const map = new Map<number, number>()
  for (const h of history) {
    const ms = Date.parse(h.readAt)
    if (Number.isNaN(ms)) continue
    const prev = map.get(h.comicId)
    if (prev === undefined || ms > prev) map.set(h.comicId, ms)
  }
  return map
}

/**
 * 该收藏在「上次阅读之后」有没有更新。
 *
 * 任一侧缺失 / 不可解析（含**从未读过**，即 `readAtMap` 里查不到）一律 `false` ——
 * 没有基准时间就只能不亮，否则刚加入收藏的书会全部亮起，角标等于失效。
 */
export function hasUpdate(comic: ComicLike, readAtMap: Map<number, number>): boolean {
  if (!comic.updatedAt) return false
  const readAt = readAtMap.get(comic.id)
  if (readAt === undefined) return false
  const updatedAt = Date.parse(comic.updatedAt)
  if (Number.isNaN(updatedAt)) return false
  return updatedAt > readAt
}
