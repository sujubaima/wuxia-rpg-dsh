// message-ui 弹窗提示：回合尾不再渲染空卡片，提示改为一次性 toast。
// WeakSet 按结果对象去重——同一条提示只弹一次，重渲染/重挂载不重复。

let host: HTMLDivElement | null = null
const toasted = new WeakSet<object>()

function ensureHost(): HTMLDivElement {
  if (host && host.isConnected) return host
  host = document.createElement('div')
  host.style.cssText = [
    'position:fixed', 'top:14px', 'left:50%', 'transform:translateX(-50%)',
    'z-index:10000', 'display:flex', 'flex-direction:column', 'gap:8px', 'align-items:center',
    'pointer-events:none',
  ].join(';')
  document.body.appendChild(host)
  return host
}

/** 弹出 message-ui 的 提示 文本；同一结果对象只弹一次。 */
export function toastWuxiaMessage(result: any): void {
  if (!result || typeof result !== 'object' || toasted.has(result)) return
  const text = String(result.提示 ?? '').trim()
  if (!text) return
  toasted.add(result)
  if (typeof document === 'undefined') return
  const item = document.createElement('div')
  item.textContent = text
  item.style.cssText = [
    'max-width:min(420px, calc(100vw - 32px))',
    'padding:9px 14px', 'border-radius:8px',
    'background:#221c16', 'border:1px solid #8a6a2a', 'color:#e8dcc4',
    'font-size:13px', 'line-height:1.55', 'text-align:center',
    'box-shadow:0 4px 18px rgba(0,0,0,0.55)',
    'opacity:0', 'transform:translateY(-6px)', 'transition:opacity .25s, transform .25s',
  ].join(';')
  ensureHost().appendChild(item)
  requestAnimationFrame(() => {
    item.style.opacity = '1'
    item.style.transform = 'translateY(0)'
  })
  window.setTimeout(() => {
    item.style.opacity = '0'
    item.style.transform = 'translateY(-6px)'
    window.setTimeout(() => item.remove(), 300)
  }, 4600)
}
