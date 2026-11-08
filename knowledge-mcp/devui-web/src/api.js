// 所有请求都走 `/api`，由 vite 代理到 FastAPI（:8899）。
// 出错时把后端返回的文本原样抛出，调试页要能看到真实原因。

async function request(path, options = {}) {
  const res = await fetch(path, options)
  const text = await res.text()
  if (!res.ok) throw new Error(`${res.status} ${res.statusText}：${text.slice(0, 300)}`)
  try {
    return JSON.parse(text)
  } catch {
    throw new Error(`返回的不是 JSON：${text.slice(0, 300)}`)
  }
}

export const getJson = (path) => request(path)

export const post = (path, body) =>
  request(path, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json; charset=utf-8' },
    body: JSON.stringify(body),
  })

export const api = {
  status: () => getJson('/api/status'),
  search: (payload) => post('/api/search', payload),
  compare: (payload) => post('/api/compare', payload),
  read: (docId) => post('/api/read', { doc_id: docId }),
  // 按检索单元回读：整节原文 + 每块的字符区间（用于分块渲染）
  section: (docId) => post('/api/section', { doc_id: docId }),
  eval: (mode, topK = 5) => getJson(`/api/eval?mode=${encodeURIComponent(mode)}&top_k=${topK}`),
  // 全量重建，约 40 秒；后端用非阻塞锁挡住并发。
  rebuild: () => post('/api/index', {}),
}
