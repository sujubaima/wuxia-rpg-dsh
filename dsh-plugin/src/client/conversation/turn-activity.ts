import { useSyncExternalStore } from 'react'

// 回合活动源：读会话 chat 快照 timeline 的最新回合号。
// 新回合一旦开始，旧回合尾部的游历卡即为过时快照——控件永久禁用、仅供回顾，
// 防止陈旧面板指令与 GM 并发写引擎状态。

export interface TurnActivity {
  subscribe: (listener: () => void) => () => void
  latestTurn: () => number | undefined
}

function noopSubscribe(): () => void {
  return () => {}
}

function noLatest(): undefined {
  return undefined
}

/** 从 uiConversation 会话绑定提炼回合活动源；绑定不可用时返回 undefined。 */
export function turnActivityOf(binding: any): TurnActivity | undefined {
  let source: any
  try {
    source = binding?.target?.('chat')
  } catch { /* chat target 未注册 */ }
  if (!source || typeof source.subscribe !== 'function' || typeof source.getSnapshot !== 'function') {
    return undefined
  }
  return {
    subscribe: (listener: () => void) => source.subscribe(listener),
    latestTurn: () => source.getSnapshot()?.timeline?.turnOrder?.at(-1),
  }
}

/** 当前会话最新回合号；无会话数据时为 undefined。 */
export function useTurnLatest(activity?: TurnActivity): number | undefined {
  return useSyncExternalStore(
    activity ? activity.subscribe : noopSubscribe,
    activity ? activity.latestTurn : noLatest,
  )
}
