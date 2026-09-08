// 极简 DOM 构造助手（仅战斗回放命令式追加用）。
export function el(tag: string, cls: string, text?: string): HTMLElement {
  const e = document.createElement(tag)
  if (cls) e.className = cls
  if (text != null) e.textContent = text
  return e
}
