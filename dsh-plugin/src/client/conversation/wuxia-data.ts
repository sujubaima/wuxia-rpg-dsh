import { applyPartyState } from './party-store'

interface WuxiaTurnData {
  readonly results: readonly any[]
}

declare module '@deepseek-ai/dsh-client-ui-conversation/client' {
  interface ConversationTurnDataMap {
    wuxia: WuxiaTurnData
  }
}

function parseWuxiaResult(content: readonly any[]): any | null {
  for (const block of content) {
    const inner = block?.type === 'tool-result' ? (block.content ?? []) : [block]
    for (const item of inner) {
      if (item?.type === 'text' && typeof item.text === 'string') {
        try {
          const data = JSON.parse(item.text)
          if (data && typeof data === 'object' && '界面' in data) return data
        } catch { /* 非 JSON */ }
      }
    }
  }
  return null
}

export const wuxiaDefinition = {
  kind: 'wuxia',
  match(event: any) {
    if (event.type === 'turn/start') return { id: String(event.data.turn), role: 'start' as const }
    if (event.type === 'tool/call') return { id: String(event.data.turn), role: 'update' as const }
    if (event.type === 'tool/result') return { id: String(event.data.turn), role: 'update' as const }
    return null
  },
  start(_context: any, match: any) {
    return {
      turn: match.event.data.turn,
      calls: {} as Record<string, string>,
      results: [] as any[],
    }
  },
  update(context: any, match: any) {
    if (match.event.type === 'tool/call') {
      const callId = String(match.event.data.callId)
      const name = match.event.data.name ?? ''
      return { ...context.state, calls: { ...context.state.calls, [callId]: name } }
    }
    if (match.event.type === 'tool/result') {
      const callId = String(match.event.data.message?.source?.callId ?? '')
      const name = context.state.calls[callId] ?? ''
      if (name !== 'wuxia_go' && name !== 'wuxia_judge') return context.state
      const content = match.event.data.message?.content ?? []
      const parsed = parseWuxiaResult(content)
      if (parsed === null) return context.state
      if (parsed.队伍状态 || parsed.体力 != null || parsed.金钱 != null || parsed.槽位 != null) {
        try {
          applyPartyState({
            体力: parsed.体力 ?? undefined,
            金钱: parsed.金钱 ?? undefined,
            队伍状态: parsed.队伍状态,
            槽位: parsed.槽位,
          })
        } catch { /* store 不可用 */ }
      }
      return { ...context.state, results: [...context.state.results, parsed] }
    }
    return context.state
  },
  buildLocationData(context: any, scope: any) {
    if (scope !== 'turn' || context.state === undefined) return null
    return {
      kind: 'turn',
      turn: context.state.turn,
      key: 'wuxia',
      value: { results: context.state.results },
    }
  },
}

export interface WuxiaTurnMatch {
  /** 本 turn 的回合号，用于对比最新回合判定卡片是否过时 */
  turn: number | undefined
  results: readonly any[]
}

export function selectWuxiaResults(owner: any): WuxiaTurnMatch | null {
  const turnData = owner?.turn?.data
  let data: any = null
  if (turnData instanceof Map) {
    data = turnData.get('wuxia')
  } else if (turnData && typeof turnData === 'object') {
    if (typeof turnData.get === 'function') data = turnData.get('wuxia')
    else data = turnData['wuxia'] ?? turnData.wuxia
  }
  if (!data || !data.results || data.results.length === 0) return null
  return { turn: owner?.turn?.turn, results: data.results }
}
