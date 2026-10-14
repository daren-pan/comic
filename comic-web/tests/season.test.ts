// 季节站标：`getSeason` 的月份边界容易写错（差一天就换季），且**同一个规则在
// `index.html` 的内联脚本里还有一份**（favicon 随季节切换）—— 两处必须一致，
// 这个测试钉住的是 `season.ts` 这一份。
import { describe, expect, it } from 'vitest'
import { getSeason, getSeasonLogo } from '../src/utils/season'

describe('getSeason —— 春 3-5 / 夏 6-8 / 秋 9-11 / 冬 12-2', () => {
  it('每个季节的起止月都对', () => {
    // 注意月份是 0-based：2 = 3 月
    expect(getSeason(new Date(2026, 2, 1))).toBe('spring') // 3/1
    expect(getSeason(new Date(2026, 4, 31))).toBe('spring') // 5/31
    expect(getSeason(new Date(2026, 5, 1))).toBe('summer') // 6/1
    expect(getSeason(new Date(2026, 7, 31))).toBe('summer') // 8/31
    expect(getSeason(new Date(2026, 8, 1))).toBe('autumn') // 9/1
    expect(getSeason(new Date(2026, 10, 30))).toBe('autumn') // 11/30
    expect(getSeason(new Date(2026, 11, 1))).toBe('winter') // 12/1
    expect(getSeason(new Date(2026, 0, 31))).toBe('winter') // 1/31
    expect(getSeason(new Date(2026, 1, 28))).toBe('winter') // 2/28
  })

  it('四季都有对应的站标资源，且路径落在 static/logo 下', () => {
    for (const month of [3, 6, 9, 12]) {
      const logo = getSeasonLogo(new Date(2026, month - 1, 15))
      expect(logo.icon).toMatch(/^\.\/static\/logo\/icon-\w+\.png$/)
      expect(logo.text).toMatch(/^\.\/static\/logo\/text-\w+\.png$/)
    }
  })
})
