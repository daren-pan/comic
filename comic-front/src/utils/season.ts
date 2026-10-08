/**
 * 季节识别 + 季节版品牌资源。
 *
 * 站标（图标 + 字标）随当前季节自动切换：春 3-5 / 夏 6-8 / 秋 9-11 / 冬 12-2。
 * 图片放在 `static/logo/`，按季节命名（`icon-<season>.png` / `text-<season>.png`），
 * 另有不带装饰的干净版 `*-default.png`（小尺寸站标 / 需要统一观感时用）。
 *
 * ⚠️ 图片已做透明化处理（字标去白底、图标去四角白边），可安全放在浅色与夜间两种底色上。
 */

export type Season = 'spring' | 'summer' | 'autumn' | 'winter'

/** 品牌资源：图标 + 字标 */
export interface BrandLogo {
  icon: string
  text: string
}

/** 按月份判断季节：春 3-5、夏 6-8、秋 9-11、冬 12/1/2。 */
export function getSeason(date: Date = new Date()): Season {
  const month = date.getMonth() + 1
  if (month >= 3 && month <= 5) return 'spring'
  if (month >= 6 && month <= 8) return 'summer'
  if (month >= 9 && month <= 11) return 'autumn'
  return 'winter'
}

/** 四季品牌资源表 */
const SEASON_LOGO: Record<Season, BrandLogo> = {
  spring: { icon: '/static/logo/icon-spring.png', text: '/static/logo/text-spring.png' },
  summer: { icon: '/static/logo/icon-summer.png', text: '/static/logo/text-summer.png' },
  autumn: { icon: '/static/logo/icon-autumn.png', text: '/static/logo/text-autumn.png' },
  winter: { icon: '/static/logo/icon-winter.png', text: '/static/logo/text-winter.png' },
}

/** 无装饰的干净版（缩到很小尺寸时更清晰） */
export const LOGO_DEFAULT: BrandLogo = {
  icon: '/static/logo/icon-default.png',
  text: '/static/logo/text-default.png',
}

/** 取当前季节的品牌资源（可传 date，便于测试其它季节） */
export function getSeasonLogo(date: Date = new Date()): BrandLogo {
  return SEASON_LOGO[getSeason(date)]
}
