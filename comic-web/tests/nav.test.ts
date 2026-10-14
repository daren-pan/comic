// 层级返回：`parentOf` 是一张**手写映射表**，最容易漏改 —— 漏改的后果是**静默跳回首页**
// （顶栏返回键不报错，只是去了错的地方）。
//
// 与后端 `api-service/tests/test_layering.py` 同一思路：把文档里的约定变成会红的断言。
import { describe, expect, it } from 'vitest'
import { parentOf } from '../src/utils/nav'

describe('parentOf —— 固定上级（层级返回）', () => {
  it('静态二级页的上级都回首页', () => {
    expect(parentOf('/rank')).toBe('/')
    expect(parentOf('/me')).toBe('/')
    expect(parentOf('/profile')).toBe('/')
    expect(parentOf('/messages')).toBe('/')
    expect(parentOf('/login')).toBe('/')
    expect(parentOf('/admin')).toBe('/')
  })

  it('管理台子页的上级是「采集管理」', () => {
    expect(parentOf('/admin/comics')).toBe('/admin')
    expect(parentOf('/admin/schedule')).toBe('/admin')
    expect(parentOf('/admin/logs')).toBe('/admin')
    expect(parentOf('/admin/users')).toBe('/admin')
  })

  it('阅读器 → 它那一部的详情页；详情 → 最近更新页', () => {
    expect(parentOf('/reader/44/2378')).toBe('/comic/44')
    expect(parentOf('/reader/44')).toBe('/comic/44')
    expect(parentOf('/comic/44')).toBe('/latest')
  })

  it('未登记的路径兜底回首页', () => {
    expect(parentOf('/unknown')).toBe('/')
    expect(parentOf('/')).toBe('/')
  })
})
