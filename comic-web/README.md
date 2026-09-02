# comic-web 前端（Vue 3 + TypeScript + Vite）

漫画聚合阅读平台的**前端实现**（架构方案见 `../漫画聚合网站_架构设计方案.md`，数据来自 `../crawler-service` 采集服务）。
当前使用**本地 mock 数据**（结构对齐后端 comic/chapter/page 表），对接真实后端时只需替换 `src/api/index.ts` 的实现。

## 页面与路由

| 路由 | 页面 | 说明 |
|---|---|---|
| `/` | 首页 | Banner + 热门榜单 + 最新更新（消费增量数据）+ 分类精选 |
| `/search` | 搜索 | 关键词（标题/作者/标签）+ 分类筛选 + 最新/最热排序 + 分页 |
| `/comic/:id` | 详情页 | 封面/简介/标签/多源标注 + 收藏 + 章节列表 |
| `/reader/:comicId/:chapterId` | 在线阅读器 | 懒加载/预加载、点按与键盘翻页、章节切换、进度记忆续读 |
| `/me` | 我的 | 最近阅读（续读/删除）+ 我的收藏 |

## 架构要点（与方案对应）

- **API 层**：`src/api/index.ts` 接口签名与后端 RESTful 接口一一对应
  （`getComics`↔`GET /api/comics`、`getChapterPages`↔`GET /api/chapters/{id}/pages`），
  组件层不感知数据来源，切换真实后端零改动；
- **阅读器**（架构方案 §4.2）：图片按需加载 + 前后页预加载、点击左右 1/3 区域翻页、
  `←/→` 键盘翻页、翻页即写入历史（localStorage 模拟用户中心），支持跨端续读；
- **收藏/历史**：localStorage 持久化，对应方案中 `POST /api/favorites`、`PUT /api/history`；
- **占位图**：封面与漫画分页均为本地生成的 SVG data URI（`src/utils/images.ts`），
  离线可用、零网络依赖，生产环境换成 OSS/CDN 图片 URL 即可（方案 §3.3）；
- **多源标注**：详情页展示 `sources` 字段，直观体现"多源聚合 + 指纹去重合并"。

## 本地运行

```bash
npm install
npm run dev        # 开发模式 http://localhost:5173
npm run build      # 生产构建 → dist/（base='./'，hash 路由，可离线双击打开）
npm run preview    # 预览构建产物
```

## 对接真实后端（待采集服务提供 HTTP API 时）

```ts
// vite.config.ts 打开代理
proxy: { '/api': { target: 'http://localhost:8080', changeOrigin: true } }

// src/api/index.ts 示例：把 mock 实现换成 fetch
export async function getComics(q: ComicQuery) {
  const params = new URLSearchParams({ ...q } as Record<string, string>)
  const res = await fetch(`/api/comics?${params}`)
  return res.json()  // { code, message, data } 统一响应格式
}
```
