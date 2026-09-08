// 引擎与聊天 API。移植自 game-gate.js(engineGo/engineJudge/fetchUi) 与 game-chat.js(send 的 SSE 部分)。
import type { Action, EngineResult } from './types'

/** go 直通：POST /api/engine，默认 method=go。 */
export async function engineGo(actions: Action[], slotOverride?: number): Promise<EngineResult> {
  return enginePost({ 槽位: slotOverride != null ? slotOverride : currentSlotRef(), 行为: actions })
}

/** judge 直通：POST /api/engine，method=judge。 */
export async function engineJudge(entries: Action[], extra?: Record<string, unknown>): Promise<EngineResult> {
  return enginePost(Object.assign({ method: 'judge', 槽位: currentSlotRef(), 行为: entries }, extra || {}))
}

/** 轻封装：仅取回引擎结果，错误吞为 {错误}。对应原 fetchUi。 */
export async function fetchUi(action: Action): Promise<EngineResult> {
  try {
    return await engineGo([action])
  } catch (e) {
    return { 错误: String(e) }
  }
}

async function enginePost(body: Record<string, unknown>): Promise<EngineResult> {
  const resp = await fetch('/api/engine', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  })
  const d = (await resp.json().catch(() => ({ 错误: '响应非 JSON' }))) as EngineResult
  // server 500 用英文 error，统一收口为中文 错误
  if ((d as any).error && !d.错误) d.错误 = (d as any).error
  return d
}

/** 当前槽位注入点：由 store 在启动时设置，避免 api 反向依赖 store 模块。 */
let _slot = 0
export function setSlotRef(v: number): void {
  _slot = v
}
function currentSlotRef(): number {
  return _slot
}

export interface StreamHandlers {
  onSession?: (sid: string) => void
  onDelta?: (text: string) => void
  onTool?: (name: string, args: string) => void
  onState?: (data: EngineResult) => void
  onError?: (msg: string) => void
  onDone?: (err: boolean, result?: string) => void
}

/** POST /api/chat 并解析 SSE 流，逐事件回调。返回 AbortController（可中止）。 */
export function streamChat(message: string, sessionId: string, h: StreamHandlers): AbortController {
  const ctrl = new AbortController()
  void (async () => {
    let resp: Response
    try {
      resp = await fetch('/api/chat', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ message, session_id: sessionId }),
        signal: ctrl.signal,
      })
    } catch (e) {
      h.onError?.('连接失败：' + (e as Error).message)
      h.onDone?.(true)
      return
    }
    if (!resp.ok) {
      h.onError?.('HTTP ' + resp.status)
      h.onDone?.(true)
      return
    }
    const reader = resp.body!.getReader()
    const dec = new TextDecoder()
    let buf = ''
    try {
      while (true) {
        const { done, value } = await reader.read()
        if (done) break
        buf += dec.decode(value, { stream: true })
        let idx: number
        while ((idx = buf.indexOf('\n\n')) !== -1) {
          const block = buf.slice(0, idx)
          buf = buf.slice(idx + 2)
          handleBlock(block, h)
        }
      }
    } catch {
      /* 读取中断：忽略 */
    }
  })()
  return ctrl
}

function handleBlock(block: string, h: StreamHandlers): void {
  let evType = ''
  let dataLine = ''
  for (const ln of block.split('\n')) {
    if (ln.startsWith('event:')) evType = ln.slice(6).trim()
    else if (ln.startsWith('data:')) dataLine += ln.slice(5).trim()
  }
  if (!dataLine) return
  let data: any
  try {
    data = JSON.parse(dataLine)
  } catch {
    return
  }
  switch (evType) {
    case 'session':
      h.onSession?.(data.session_id)
      break
    case 'delta':
      h.onDelta?.(data.text || '')
      break
    case 'tool':
      h.onTool?.(data.name, data.arguments || '')
      break
    case 'state':
      h.onState?.(data)
      break
    case 'error':
      h.onError?.(data.message || '')
      break
    case 'done':
      h.onDone?.(!!data.error, data.result)
      break
  }
}
