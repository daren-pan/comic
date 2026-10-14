// 分页列表的共享模式 —— 抽自 5 个页面里**逐字重复**的那段状态机（2026-10-13）。
//
// ## 抽之前长什么样
//
// `pages/latest` 与 `pages/rank` 的 `load()` / `loadMore()` / `reqId` 三块**一字不差**
// （只有 fetcher 的参数不同）；`pages/search`、`pages/admin/comics`、
// `pages/admin/logs` 又各自抄了一遍带页码跳转的变体。
//
// ## 这段逻辑看着简单，但有三处踩过坑的细节 —— 抄漏任何一处都会出问题
//
// 1. **竞态令牌**（`reqId`）：切标签 / 切排序会连发请求，只认最后一次的结果 ——
//    否则旧响应会盖掉新榜（`pages/rank` 的原注释）；
// 2. **追加失败要回退页码**：否则下次触底会**跳过失败的那一页，永久少一页数据**；
// 3. **`ready` 只在「自己是最后一次请求」时置位**：乱序返回时若提前置位，
//    首屏会先闪一下"暂无数据"再出内容。
//
// ## 两种用法（同一份状态机）
//
// - **触底追加**：把 `loadMore` 交给 `onReachBottom`（latest / rank）
// - **页码跳转**：`goPage(n)` + `totalPages`（search / admin-comics / admin-users）
//   —— ⚠️ 与追加是**两种语义**：翻页要**替换**列表内容，不是往后接。两者共用
//   同一套竞态/错误处理，但 `items` 的写法不同（见 `goPage` 的注释）。
//
// ## 与 UI 的分工
//
// 它只管状态，**不碰任何 DOM/样式** —— 三态显示交给 `components/StateView.vue`：
//
//   const { items, loading, ready, error, loadMore, reload } = usePagedList(fetcher)
//   onReachBottom(loadMore)
//
//   <StateView :loading="loading && !ready" :error="error" :empty="!items.length">
//     …
//   </StateView>
//
// ⚠️ `loading && !ready` 这个组合是刻意的：`loading` 在**追加**时也为真，
// 直接传它会让已有列表被"加载中"替换掉。
import { computed, ref, type ComputedRef, type Ref } from 'vue'

/** fetcher 的返回形状 —— 与后端 `PageResult<T>` 对应（`items` + `total` 两个字段就够） */
export interface PagePayload<T> {
  items: T[]
  total: number
}

export interface UsePagedListOptions {
  /**
   * 每页条数（默认 20）。
   * ⚠️ 移动端列表页通常取 **3 的倍数**：网格是 3 列，末行不留空
   * （`pages/search` 的 `pageSize = 18` 就是这么来的）。
   */
  pageSize?: number
  /** 是否立即拉第一页（默认 true；需要先等其它数据就绪时传 false） */
  immediate?: boolean
}

export interface PagedList<T> {
  items: Ref<T[]>
  total: Ref<number>
  page: Ref<number>
  pageSize: number
  /** 有请求在飞（首屏与追加**共用**这个标志，见文件头 ⚠️） */
  loading: Ref<boolean>
  /** 首屏是否已出过结果 —— 区分「加载中」与「确实没有数据」 */
  ready: Ref<boolean>
  /** 最近一次失败的中文原因（空串 = 无错）；成功一次即清空 */
  error: Ref<string>
  hasMore: ComputedRef<boolean>
  totalPages: ComputedRef<number>
  /** 拉取；`reset = true` 从第一页重来（切筛选条件时用） */
  load: (reset?: boolean) => Promise<void>
  /** 触底追加：内置「加载中不重入」「已拉完不再请求」 */
  loadMore: () => void
  /** 跳到第 n 页（**替换**列表内容；越界夹到 `1..totalPages`；失败回退页码） */
  goPage: (n: number) => Promise<void>
  /** 重拉**当前页**（保持页码；替换语义）—— 行内操作改动了数据后刷新用（如补章后） */
  refresh: () => Promise<void>
  /** 等价于 `load(true)`，语义化入口 */
  reload: () => void
}

export function usePagedList<T>(
  fetcher: (page: number, pageSize: number) => Promise<PagePayload<T>>,
  options: UsePagedListOptions = {},
): PagedList<T> {
  const pageSize = options.pageSize ?? 20

  const items = ref([]) as Ref<T[]>
  const total = ref(0)
  const page = ref(1)
  const loading = ref(false)
  const ready = ref(false)
  const error = ref('')

  /** 请求序号 —— 并发 / 乱序时只认最后一次（见文件头 ①） */
  let reqId = 0

  const hasMore = computed(() => items.value.length < total.value)
  const totalPages = computed(() => Math.max(1, Math.ceil(total.value / pageSize)))

  async function load(reset = false): Promise<void> {
    const id = ++reqId
    if (reset) {
      page.value = 1
      items.value = [] as T[]
      total.value = 0
      error.value = ''
    }
    loading.value = true
    try {
      const res = await fetcher(page.value, pageSize)
      if (id !== reqId) return // 已有更新的请求发出 → 丢弃本次结果
      items.value = reset ? res.items : items.value.concat(res.items)
      total.value = res.total
      error.value = ''
    } catch (e) {
      if (id !== reqId) return
      if (reset) {
        items.value = [] as T[]
        total.value = 0
      } else {
        // 追加失败 → 页码回退，下次触底重试（见文件头 ②）
        page.value = Math.max(1, page.value - 1)
      }
      error.value = (e as Error)?.message || '加载失败'
    } finally {
      if (id === reqId) {
        // 见文件头 ③
        loading.value = false
        ready.value = true
      }
    }
  }

  function loadMore(): void {
    if (loading.value || !hasMore.value) return
    page.value += 1
    void load()
  }

  /**
   * 跳到第 n 页 —— **替换**语义（与 `loadMore` 的追加区分）。
   *
   * 翻页失败时**页码回退到原页**：否则会出现「页码已前进、列表还是旧数据」的错位，
   * 用户再点「下一页」就连续丢页（与 `load` 的追加失败回退同一思路：**页码必须与列表内容一致**）。
   */
  async function goPage(n: number): Promise<void> {
    const target = Math.min(Math.max(1, Math.round(n)), totalPages.value)
    if (target === page.value || loading.value) return
    const prev = page.value
    const id = ++reqId
    page.value = target          // 先更新页码（UI 立即响应），失败再回退
    loading.value = true
    try {
      const res = await fetcher(target, pageSize)
      if (id !== reqId) return // 已有更新的请求发出 → 丢弃本次结果
      items.value = res.items      // ← 替换（loadMore 是 concat）
      total.value = res.total
      error.value = ''
    } catch (e) {
      if (id !== reqId) return
      page.value = prev
      error.value = (e as Error)?.message || '加载失败'
    } finally {
      if (id === reqId) {
        loading.value = false
        ready.value = true
      }
    }
  }

  /**
   * 重拉**当前页**（保持页码）—— 行内操作改了数据后刷新用。
   * 与 `goPage` 的区别：页码不动（失败也无需回退，列表保持原内容）。
   */
  async function refresh(): Promise<void> {
    const id = ++reqId
    loading.value = true
    try {
      const res = await fetcher(page.value, pageSize)
      if (id !== reqId) return
      items.value = res.items
      total.value = res.total
      error.value = ''
    } catch (e) {
      if (id !== reqId) return
      error.value = (e as Error)?.message || '加载失败'
    } finally {
      if (id === reqId) {
        loading.value = false
        ready.value = true
      }
    }
  }

  function reload(): void {
    void load(true)
  }

  if (options.immediate !== false) void load(true)

  return {
    items, total, page, pageSize, loading, ready, error,
    hasMore, totalPages, load, loadMore, goPage, refresh, reload,
  }
}
