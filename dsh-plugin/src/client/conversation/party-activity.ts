import { useSyncExternalStore } from 'react'
import { selectWuxiaResults } from './wuxia-data'
import type { PartyStatePayload } from './party-store'

// 队伍数据源：从会话 chat timeline 派生最新队伍状态。
// timeline 由会话事件窗口重建/缓存，切会话或刷新页面后依然可靠；
// 弥补内存 party store 切会话即清、事件不重放导致的浮窗数据消失。

export interface PartySource {
  subscribe: (listener: () => void) => () => void
  latest: () => PartyStatePayload | null
}

function noopSubscribe(): () => void {
  return () => {}
}

function noLatest(): null {
  return null
}

function samePayload(a: PartyStatePayload | null, b: PartyStatePayload | null): boolean {
  if (a === b) return true
  if (!a || !b) return false
  return a.体力 === b.体力
    && a.金钱 === b.金钱
    && a.槽位 === b.槽位
    && JSON.stringify(a.队伍状态) === JSON.stringify(b.队伍状态)
}

/** 按 turnOrder 顺序取最后一个含队伍字段（体力/金钱/队伍状态/槽位）的引擎结果。 */
function computePayload(timeline: any): PartyStatePayload | null {
  const order = timeline?.turnOrder
  const turns = timeline?.turns
  if (!Array.isArray(order) || !turns || typeof turns.get !== 'function') return null
  let payload: PartyStatePayload | null = null
  for (const turnNumber of order) {
    // selectWuxiaResults 的 owner 约定是 { turn: TurnLocation }
    const match = selectWuxiaResults({ turn: turns.get(turnNumber) })
    if (!match) continue
    for (const result of match.results) {
      if (result && (result.队伍状态 || result.体力 != null || result.金钱 != null || result.槽位 != null)) {
        payload = {
          体力: result.体力 ?? undefined,
          金钱: result.金钱 ?? undefined,
          队伍状态: result.队伍状态,
          槽位: result.槽位,
        }
      }
    }
  }
  return payload
}

/** 从 uiConversation 会话绑定提炼队伍数据源；绑定不可用时返回 undefined。 */
export function partySourceOf(binding: any): PartySource | undefined {
  let source: any
  try {
    source = binding?.target?.('chat')
  } catch { /* chat target 未注册 */ }
  if (!source || typeof source.subscribe !== 'function' || typeof source.getSnapshot !== 'function') {
    return undefined
  }
  // getSnapshot 须引用稳定：值未变时返回同一对象，避免 useSyncExternalStore 死循环
  let cachedSnapshot: any
  let hasSnapshot = false
  let cachedValue: PartyStatePayload | null = null
  return {
    subscribe: (listener: () => void) => source.subscribe(listener),
    latest: () => {
      const snapshot = source.getSnapshot()
      if (hasSnapshot && snapshot === cachedSnapshot) return cachedValue
      const value = computePayload(snapshot?.timeline)
      cachedSnapshot = snapshot
      hasSnapshot = true
      if (!samePayload(value, cachedValue)) cachedValue = value
      return cachedValue
    },
  }
}

/** 当前会话 timeline 派生的最新队伍状态。 */
export function usePartySource(source?: PartySource): PartyStatePayload | null {
  return useSyncExternalStore(
    source ? source.subscribe : noopSubscribe,
    source ? source.latest : noLatest,
  )
}
