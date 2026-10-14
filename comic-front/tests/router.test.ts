// `utils/router.ts` 的两张映射表 —— 最容易漏改、且漏改后果最隐蔽的地方。
//
// 为什么值得专门测：新增页面时若忘了在 `STATIC` 里登记，`toUniUrl` 会走兜底
// **静默跳回首页**（只在控制台留一句 warn，没人会看）。2026-10-06 就这么踩过
// 一次（漏登记 `/admin/schedule` → 点「定时任务」跳到了首页）。
//
// 这里把"已登记的每一项"逐个钉住：**表被改坏就立刻红**。
import { describe, expect, it } from 'vitest'
import { parentOf, setRoute, toUniUrl } from '../src/utils/router'

// 注意路径：本文件住在 comic-front/tests/，与被测的 src/ 平级

describe('toUniUrl —— web 路径 → uni 页面地址（去程映射）', () => {
  it('STATIC 表里的每一项都能转（漏登记会静默跳首页）', () => {
    const expected: Record<string, string> = {
      '/': 'pages/index/index',
      '/search': 'pages/search/index',
      '/latest': 'pages/latest/index',
      '/rank': 'pages/rank/index',
      '/me': 'pages/me/index',
      '/profile': 'pages/profile/index',
      '/messages': 'pages/messages/index',
      '/login': 'pages/login/index',
      '/admin': 'pages/admin/index',
      '/admin/logs': 'pages/admin/logs',
      '/admin/users': 'pages/admin/users',
      '/admin/schedule': 'pages/admin/schedule',
      '/admin/comics': 'pages/admin/comics',
    }
    for (const [web, page] of Object.entries(expected)) {
      expect(toUniUrl(web), `${web} 应转到 ${page}`).toBe(page)
    }
  })

  it('带参页面按正则解析（详情 / 阅读器）', () => {
    expect(toUniUrl('/comic/44')).toBe('pages/comic/index?id=44')
    expect(toUniUrl('/reader/44/100')).toBe('pages/reader/index?comicId=44&chapterId=100')
  })

  it('query 拼接并 URL 编码', () => {
    expect(toUniUrl({ path: '/search', query: { keyword: '海贼王' } })).toBe(
      `pages/search/index?keyword=${encodeURIComponent('海贼王')}`,
    )
    // 空值被跳过（不产生 `keyword=`）
    expect(toUniUrl({ path: '/search', query: { keyword: '', category: '科幻' } })).toBe(
      `pages/search/index?category=${encodeURIComponent('科幻')}`,
    )
  })

  it('`{ query }` 不给 path = 在当前路径上改查询（vue-router 语义）', () => {
    // 分类页的筛选就是这么调的：`router.replace({ query: {...} })`
    setRoute('/search', { category: '全部' })
    expect(toUniUrl({ query: { category: '科幻' } })).toBe(
      `pages/search/index?category=${encodeURIComponent('科幻')}`,
    )
  })

  it('路径里自带的 query 会被解析出来', () => {
    expect(toUniUrl('/search?category=科幻')).toBe(
      `pages/search/index?category=${encodeURIComponent('科幻')}`,
    )
  })

  it('未登记的路径兜底回首页（并留 warn）', () => {
    expect(toUniUrl('/not-registered')).toBe('pages/index/index')
  })
})

describe('parentOf —— 层级返回的固定上级（回程映射）', () => {
  it('静态二级页回首页', () => {
    for (const p of ['/rank', '/me', '/profile', '/messages', '/login', '/admin']) {
      expect(parentOf(p), `${p} 的上级应是首页`).toBe('/')
    }
  })

  it('管理台子页回「采集管理」', () => {
    for (const p of ['/admin/logs', '/admin/users', '/admin/schedule', '/admin/comics']) {
      expect(parentOf(p)).toBe('/admin')
    }
  })

  it('阅读器回它那一部的详情页；详情页回最近更新页', () => {
    expect(parentOf('/reader/44/100')).toBe('/comic/44')
    expect(parentOf('/comic/44')).toBe('/latest')
  })

  it('未登记的路径退回首页（兜底）', () => {
    expect(parentOf('/unknown')).toBe('/')
  })
})
