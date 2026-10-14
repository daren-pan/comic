// 展示格式化 —— 全站唯一的一份（2026-10-13 收敛）。
//
// ## 为什么要有它
//
// 同一件事此前在 **8 个文件**里各写一遍，而且**同名不同义**：
// `fmtTime` 在 `pages/me` 是 `YYYY-MM-DD HH:mm`，在 `pages/comic` 却是 `M月D日` ——
// 光看调用点根本判断不出会显示成什么。收敛之后，**函数名即口径**。
//
// | 函数 | 口径 | 原先散落在 |
// |---|---|---|
// | `formatDateTime` | `YYYY-MM-DD HH:mm`，空值 → `—` | me / admin-index / admin-schedule |
// | `formatRelative` | `N 分钟前` / `N 小时前` / `N 天前` | 首页 |
// | `formatMonthDay` | `M月D日` | admin-comics / comic-detail |
// | `formatCommentTime` | 今天 → `HH:mm`，否则 `M月D日` | comic-detail |
// | `formatInterval` | `30s` / `15min` / `6h` | admin-index |
// | `formatHeat` | `9999` / `1.2 万` | rank |
//
// ⚠️ 这些是**纯函数**（不依赖响应式状态、不需要组件实例），所以住 `utils/` 而**不是**
// `composables/` —— 与 `utils/season.ts` 同类。composables 留给真正需要响应式的那类
// （目前只有 `usePagedList`）。
//
// ⚠️ `stores/message.ts` 的 `fmtMsgTime`（`MM-DD HH:mm`）**刻意没并进来**：消息列表是
// 行式布局、需要更紧凑的格式，与这里的 `formatDateTime` 是两种口径，合并必然改掉
// 某一处的显示。

const pad = (n: number): string => String(n).padStart(2, '0')

/**
 * `YYYY-MM-DD HH:mm`；空值或非法时间 → `—`。
 *
 * 管理台表格里"没有值"要能一眼看出来，所以空值给破折号而不是空串。
 * （多加了非法时间的判断：旧实现遇到坏数据会显示成 `NaN-NaN-NaN NaN:NaN`。）
 */
export function formatDateTime(iso: string | null | undefined): string {
  if (!iso) return '—'
  const d = new Date(iso)
  if (Number.isNaN(d.getTime())) return '—'
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())} ${pad(d.getHours())}:${pad(d.getMinutes())}`
}

/** 相对时间：`N 分钟前` / `N 小时前` / `N 天前`（不足 1 分钟按 1 分钟算） */
export function formatRelative(iso: string): string {
  const diff = Date.now() - new Date(iso).getTime()
  const mins = Math.floor(diff / 60000)
  if (mins < 60) return `${Math.max(mins, 1)} 分钟前`
  const hours = Math.floor(mins / 60)
  if (hours < 24) return `${hours} 小时前`
  return `${Math.floor(hours / 24)} 天前`
}

/** `M月D日` —— 短日期，省略年份（漫画的更新/阅读时间跨年不敏感） */
export function formatMonthDay(iso: string): string {
  const d = new Date(iso)
  return `${d.getMonth() + 1}月${d.getDate()}日`
}

/** 评论时间：**今天只给时分**，其余给 `M月D日`（与列表的日期分组粒度一致） */
export function formatCommentTime(iso: string): string {
  const d = new Date(iso)
  const today = new Date()
  const sameDay =
    d.getFullYear() === today.getFullYear() &&
    d.getMonth() === today.getMonth() &&
    d.getDate() === today.getDate()
  return sameDay
    ? `${pad(d.getHours())}:${pad(d.getMinutes())}`
    : `${d.getMonth() + 1}月${d.getDate()}日`
}

/** 采集间隔（秒）→ `30s` / `15min` / `6h`（只有整点小时才用 `h`） */
export function formatInterval(sec: number): string {
  if (sec < 60) return `${sec}s`
  if (sec % 3600 === 0) return `${sec / 3600}h`
  return `${Math.round(sec / 60)}min`
}

/** 热度：1 万以上折算成 `x.x 万`（榜单里不让数字占版面） */
export function formatHeat(v: number): string {
  if (v >= 10000) return `${(v / 10000).toFixed(1).replace(/\.0$/, '')} 万`
  return String(v)
}
