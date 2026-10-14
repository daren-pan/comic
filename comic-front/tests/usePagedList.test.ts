// 分页状态机的行为守卫 —— 2026-10-13 新增 `goPage` 的**替换语义**与**失败回退**时加。
//
// 重点钉住两件事：
// 1. **翻页是替换、触底是追加** —— 两种语义搞混会让页面列出错误的内容
//    （把翻页写成追加：第 3 页会显示 1~30 条；把追加写成替换：触底只剩最后一页）；
// 2. **翻页失败页码必须回退** —— 否则「页码已前进、列表还是旧数据」，
//    用户再点「下一页」就连续跳页、丢页。
import { describe, expect, it, vi } from 'vitest'
import { usePagedList } from '../src/composables/usePagedList'

/** 假 fetcher：按页产出连续编号（第 n 页 → 从 (n-1)*pageSize+1 开始）；`failOn` 指定某页抛错 */
function makeFetcher(total: number, pageSize: number, failOn?: number) {
  return vi.fn(async (page: number) => {
    if (failOn !== undefined && page === failOn) throw new Error('网络错误')
    const start = (page - 1) * pageSize
    const count = Math.max(0, Math.min(pageSize, total - start))
    return {
      items: Array.from({ length: count }, (_, i) => start + i + 1),
      total,
    }
  })
}

const range = (from: number, to: number) => Array.from({ length: to - from + 1 }, (_, i) => from + i)

describe('usePagedList · 翻页（goPage）', () => {
  it('翻页**替换**列表内容（不是追加）', async () => {
    const fetcher = makeFetcher(50, 10)
    const list = usePagedList(fetcher, { pageSize: 10, immediate: false })
    await list.load(true)
    expect(list.items.value).toEqual(range(1, 10))

    await list.goPage(3)
    expect(list.page.value).toBe(3)
    // 只有第 3 页的数据 —— 若是追加语义，这里会是 1~30
    expect(list.items.value).toEqual(range(21, 30))
    expect(list.total.value).toBe(50)
  })

  it('越界页码夹到 [1, totalPages]', async () => {
    const fetcher = makeFetcher(25, 10) // totalPages = 3
    const list = usePagedList(fetcher, { pageSize: 10, immediate: false })
    await list.load(true)

    await list.goPage(999)
    expect(list.page.value).toBe(3)
    expect(list.items.value).toEqual(range(21, 25))

    await list.goPage(-5)
    expect(list.page.value).toBe(1)
    expect(list.items.value).toEqual(range(1, 10))
  })

  it('翻页失败 → 页码回退，列表保持原内容', async () => {
    const fetcher = makeFetcher(50, 10, 3) // 第 3 页抛错
    const list = usePagedList(fetcher, { pageSize: 10, immediate: false })
    await list.load(true)

    await list.goPage(3)
    expect(list.page.value).toBe(1) // 回退到原页
    expect(list.items.value).toEqual(range(1, 10)) // 内容未变
    expect(list.error.value).toBe('网络错误')
  })

  it('目标页 === 当前页时不再发请求', async () => {
    const fetcher = makeFetcher(50, 10)
    const list = usePagedList(fetcher, { pageSize: 10, immediate: false })
    await list.load(true)

    fetcher.mockClear()
    await list.goPage(1)
    expect(fetcher).not.toHaveBeenCalled()
  })
})

describe('usePagedList · refresh / loadMore', () => {
  it('refresh 重拉**当前页**（页码不动）', async () => {
    const fetcher = makeFetcher(50, 10)
    const list = usePagedList(fetcher, { pageSize: 10, immediate: false })
    await list.load(true)
    await list.goPage(2)

    await list.refresh()
    expect(list.page.value).toBe(2)
    expect(list.items.value).toEqual(range(11, 20))
    expect(fetcher).toHaveBeenLastCalledWith(2, 10)
  })

  it('loadMore 是**追加**（与 goPage 的替换语义区分）', async () => {
    const fetcher = makeFetcher(50, 10)
    const list = usePagedList(fetcher, { pageSize: 10, immediate: false })
    await list.load(true)

    list.loadMore()
    await vi.waitFor(() => expect(list.items.value).toHaveLength(20))
    expect(list.items.value).toEqual(range(1, 20))
    expect(list.page.value).toBe(2)
  })
})
