// 底栏图标：自绘 SVG → base64 data URI，喂给 uni 的 <image>。
//
// 为什么不把裸 <svg> 写进模板：项目约定「模板只用 uni 组件」，<image> 是 uni 组件、
//   三端（H5 桌面 / H5 移动 / App）行为一致，而裸 <svg> 绕过了这层。
// 为什么不引图标库：只为 3 个图标引依赖不划算，自绘零依赖、样式可控。
//
// 颜色写死在 SVG 里（<image> 不认 currentColor），所以选中/未选中各生成一份，
// 且**夜间主题要再生成一套** —— 默认态用的是 --text-2，夜间该值变亮，图标不跟着换就看不见了。
//
// 用 base64 而非 encodeURIComponent：base64 data URI 是各端 <image> 最通用的形式。
// 不用 btoa：部分运行环境没有这个全局；SVG 内容全是 ASCII，故只需 ASCII 版编码器。

const B64CHARS = 'ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+/'

// 只处理 ASCII（SVG 里不会有非 ASCII 字符），与 Buffer.toString('base64') 结果一致
function b64ascii(s: string): string {
  let out = ''
  for (let i = 0; i < s.length; i += 3) {
    const c1 = s.charCodeAt(i)
    const c2 = i + 1 < s.length ? s.charCodeAt(i + 1) : NaN
    const c3 = i + 2 < s.length ? s.charCodeAt(i + 2) : NaN
    const n = (c1 << 16) | ((c2 || 0) << 8) | (c3 || 0)
    out +=
      B64CHARS[(n >> 18) & 63] +
      B64CHARS[(n >> 12) & 63] +
      (isNaN(c2) ? '=' : B64CHARS[(n >> 6) & 63]) +
      (isNaN(c3) ? '=' : B64CHARS[n & 63])
  }
  return out
}

// 与 style.css 的 `:root` / `.theme-dark` 里的 --text-2、--primary 保持一致（改一处要改两处）
const OFF_LIGHT = '#6f675f' // 明亮主题的 --text-2
const OFF_DARK = '#a69d94' // 夜间主题的 --text-2
const ON_LIGHT = '#ff5a36' // 明亮主题的 --primary
const ON_DARK = '#ff6b4a' // 夜间主题的 --primary

function icon(body: string, color: string): string {
  const svg =
    '<svg xmlns="http://www.w3.org/2000/svg" width="24" height="24" viewBox="0 0 24 24" fill="none"' +
    ` stroke="${color}" stroke-width="1.9" stroke-linecap="round" stroke-linejoin="round">` +
    body +
    '</svg>'
  return 'data:image/svg+xml;base64,' + b64ascii(svg)
}

// 首页：屋顶 + 屋身 + 门
const HOME =
  '<path d="M3.2 9.7 12 2.9l8.8 6.8"/><path d="M5.5 8.9V20a1 1 0 0 0 1 1h11a1 1 0 0 0 1-1V8.9"/><path d="M9.7 21v-6.1h4.6V21"/>'
// 最近更新：时钟
const CLOCK = '<circle cx="12" cy="12" r="8.8"/><path d="M12 6.9v5.5l3.6 2.1"/>'
// 分类：四宫格
const GRID =
  '<rect x="3.4" y="3.4" width="7.2" height="7.2" rx="1.7"/><rect x="13.4" y="3.4" width="7.2" height="7.2" rx="1.7"/><rect x="3.4" y="13.4" width="7.2" height="7.2" rx="1.7"/><rect x="13.4" y="13.4" width="7.2" height="7.2" rx="1.7"/>'

/** 底栏 tab 图标：`off` 默认态、`on` 选中态（主题橙）。两套主题各一份。 */
function tabIcons(off: string, on: string) {
  return {
    home: { off: icon(HOME, off), on: icon(HOME, on) },
    latest: { off: icon(CLOCK, off), on: icon(CLOCK, on) },
    category: { off: icon(GRID, off), on: icon(GRID, on) },
  }
}

/** 明亮主题（默认） */
export const TAB_ICONS = tabIcons(OFF_LIGHT, ON_LIGHT)
/** 夜间主题 —— 用法与 TAB_ICONS 完全一致，由 Layout 按当前主题选用 */
export const TAB_ICONS_DARK = tabIcons(OFF_DARK, ON_DARK)
