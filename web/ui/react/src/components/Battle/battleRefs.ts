// 战斗卡面 DOM 注册表：回放动画命令式触发真实节点（与原 getElementById 同技术）。
// 卡片挂载时通过 ref 回调注册，卸载时注销。
export const cardRefs = new Map<string, HTMLDivElement>()

export function registerCard(name: string, el: HTMLDivElement | null): void {
  if (el) cardRefs.set(name, el)
  else cardRefs.delete(name)
}

export function getCard(name: string): HTMLDivElement | undefined {
  return cardRefs.get(name)
}
