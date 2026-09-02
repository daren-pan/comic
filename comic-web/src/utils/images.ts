// 占位图片生成器：封面与漫画分页图均为 SVG data URI，离线可用、零网络依赖。
// 生产环境替换为真实 OSS/CDN 图片 URL 即可（架构方案 §3.3 图片资源层）。

/** 按字符串生成稳定的 0-360 色相 */
function hueOf(seed: string): number {
  let h = 0
  for (let i = 0; i < seed.length; i++) h = (h * 31 + seed.charCodeAt(i)) % 360
  return h
}

/** 生成漫画封面（海报风：色块 + 渐变 + 标题文字） */
export function makeCover(title: string, author: string, seed: string): string {
  const hue = hueOf(seed)
  const hue2 = (hue + 40) % 360
  const svg = `<svg xmlns="http://www.w3.org/2000/svg" width="300" height="400" viewBox="0 0 300 400">
  <defs>
    <linearGradient id="g" x1="0" y1="0" x2="1" y2="1">
      <stop offset="0" stop-color="hsl(${hue},72%,46%)"/>
      <stop offset="1" stop-color="hsl(${hue2},70%,30%)"/>
    </linearGradient>
  </defs>
  <rect width="300" height="400" fill="url(#g)"/>
  <circle cx="230" cy="80" r="70" fill="hsl(${hue2},70%,60%)" opacity="0.35"/>
  <circle cx="60" cy="330" r="90" fill="hsl(${hue},80%,70%)" opacity="0.25"/>
  <rect x="24" y="290" width="252" height="4" rx="2" fill="#fff" opacity="0.7"/>
  <text x="150" y="340" text-anchor="middle" font-family="'Microsoft YaHei',sans-serif" font-size="30" font-weight="bold" fill="#fff">${title}</text>
  <text x="150" y="372" text-anchor="middle" font-family="'Microsoft YaHei',sans-serif" font-size="14" fill="#ffe9e0" opacity="0.9">${author}</text>
</svg>`
  return 'data:image/svg+xml;charset=utf-8,' + encodeURIComponent(svg)
}

/** 生成漫画分页图（模拟一格漫画页，带页号与画格） */
export function makePageImage(comicTitle: string, chapterTitle: string, pageNo: number, total: number): string {
  const hue = (hueOf(comicTitle) + pageNo * 12) % 360
  const bg = `hsl(${hue},22%,94%)`
  const panel = `hsl(${(hue + 20) % 360},30%,82%)`
  const svg = `<svg xmlns="http://www.w3.org/2000/svg" width="720" height="1020" viewBox="0 0 720 1020">
  <rect width="720" height="1020" fill="${bg}"/>
  <rect x="36" y="40" width="648" height="420" rx="8" fill="${panel}" stroke="hsl(${hue},40%,55%)" stroke-width="4"/>
  <rect x="60" y="64" width="200" height="260" rx="6" fill="hsl(${(hue + 60) % 360},45%,78%)"/>
  <rect x="288" y="64" width="372" height="160" rx="6" fill="hsl(${(hue + 120) % 360},45%,80%)"/>
  <rect x="288" y="240" width="372" height="84" rx="6" fill="hsl(${(hue + 180) % 360},45%,76%)"/>
  <rect x="36" y="486" width="648" height="250" rx="8" fill="${panel}" stroke="hsl(${hue},40%,55%)" stroke-width="4"/>
  <circle cx="500" cy="600" r="70" fill="hsl(${(hue + 90) % 360},55%,70%)" opacity="0.8"/>
  <rect x="60" y="560" width="180" height="120" rx="6" fill="hsl(${(hue + 150) % 360},45%,80%)"/>
  <rect x="36" y="762" width="648" height="190" rx="8" fill="${panel}" stroke="hsl(${hue},40%,55%)" stroke-width="4"/>
  <text x="360" y="900" text-anchor="middle" font-family="'Microsoft YaHei',sans-serif" font-size="26" fill="hsl(${hue},50%,35%)">${pageNo} / ${total}</text>
  <text x="360" y="970" text-anchor="middle" font-family="'Microsoft YaHei',sans-serif" font-size="15" fill="#888">${chapterTitle} · 第 ${pageNo} 页（占位图）</text>
</svg>`
  return 'data:image/svg+xml;charset=utf-8,' + encodeURIComponent(svg)
}
