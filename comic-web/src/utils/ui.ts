// 弹窗兼容层 —— 全站唯一的弹窗出口（不要直接用 window.alert / confirm，ESLint 已禁）。
//
// 基于原生 `<dialog>` 元素（自带焦点管理 + Esc 关闭 + ::backdrop），
// 样式挂 `.app-modal` 系列类（见 style.css，走项目 CSS 变量、随主题切换）。
// 调用点只关心「提示一句」/「确认还是取消」，Promise 语义与约定保持不变。

interface ModalOptions {
  title: string
  content: string
  showCancel: boolean
}

/** 打开一个模态框：确定 → true；取消 / Esc / 关闭 → false */
function openModal({ title, content, showCancel }: ModalOptions): Promise<boolean> {
  return new Promise((resolve) => {
    const dlg = document.createElement('dialog')
    dlg.className = 'app-modal'

    const h = document.createElement('div')
    h.className = 'app-modal-title'
    h.textContent = title

    const p = document.createElement('div')
    p.className = 'app-modal-text'
    p.textContent = content

    const bar = document.createElement('div')
    bar.className = 'app-modal-bar'

    let settled = false
    const finish = (ok: boolean) => {
      if (settled) return
      settled = true
      dlg.close()
      dlg.remove()
      resolve(ok)
    }

    if (showCancel) {
      const cancel = document.createElement('button')
      cancel.className = 'btn ghost app-modal-cancel'
      cancel.textContent = '取消'
      cancel.addEventListener('click', () => finish(false))
      bar.appendChild(cancel)
    }
    const okBtn = document.createElement('button')
    okBtn.className = 'btn app-modal-ok'
    okBtn.textContent = showCancel ? '确定' : '知道了'
    okBtn.addEventListener('click', () => finish(true))
    bar.appendChild(okBtn)

    dlg.append(h, p, bar)
    // Esc 关闭：cancel 事件在关闭前触发，统一当「取消」
    dlg.addEventListener('cancel', () => finish(false))
    document.body.appendChild(dlg)
    dlg.showModal()
    okBtn.focus()
  })
}

/** 提示弹窗（只有一个「知道了」）。失败也 resolve —— 弹窗失败不该打断业务流程。 */
export function showAlert(content: string, title = '提示'): Promise<void> {
  return openModal({ title, content, showCancel: false }).then(() => undefined)
}

/** 确认弹窗 → `true` = 确定，`false` = 取消（或弹窗不可用时保守当取消） */
export function showConfirm(content: string, title = '请确认'): Promise<boolean> {
  return openModal({ title, content, showCancel: true })
}

// ---- 轻提示 / 等待遮罩（原来分别是 uni.showToast 与 uni.showLoading/hideLoading）----

let toastEl: HTMLElement | null = null
let toastTimer: ReturnType<typeof setTimeout> | null = null

/** 底部轻提示（1.8s 自动消失；同屏只保留一条） */
export function showToast(title: string): void {
  if (toastTimer) clearTimeout(toastTimer)
  if (!toastEl) {
    toastEl = document.createElement('div')
    toastEl.className = 'app-toast'
    document.body.appendChild(toastEl)
  }
  toastEl.textContent = title
  toastEl.classList.add('on')
  toastTimer = setTimeout(() => toastEl?.classList.remove('on'), 1800)
}

let loadingEl: HTMLElement | null = null

/** 全屏等待遮罩（上传等）；**必须与 `hideLoading()` 配对** */
export function showLoading(title = '处理中…'): void {
  if (!loadingEl) {
    loadingEl = document.createElement('div')
    loadingEl.className = 'app-loading'
    loadingEl.innerHTML =
      '<div class="app-loading-box"><span class="app-loading-spin"></span><span class="app-loading-text"></span></div>'
    document.body.appendChild(loadingEl)
  }
  const text = loadingEl.querySelector('.app-loading-text')
  if (text) text.textContent = title
  loadingEl.classList.add('on')
}

/** 关掉等待遮罩 */
export function hideLoading(): void {
  loadingEl?.classList.remove('on')
}
