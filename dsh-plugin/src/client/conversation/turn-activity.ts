import { useSyncExternalStore } from 'react'
import { selectWuxiaResults } from './wuxia-data'

// 回合活动源：读会话 chat 快照 timeline。
// 新回合产出更新的卡片后，旧回合尾部的游历卡即为过时快照——控件永久禁用、仅供回顾，
// 防止陈旧面板指令与 GM 并发写引擎状态。
// 例外：纯 message-ui 提示回合表示引擎拒绝/未推进状态，不作为置灰依据，
// 最新有效卡所在回合仍视为「当前」，上一轮卡片保持可用。

export interface TurnActivity {
  subscribe: (listener: () => void) => () => void
  latestTurn: () => number | undefined
  /** 最新「有效卡片」回合号：纯 message-ui 回合跳过，无引擎结果的回合视为遮挡 */
  latestCardTurn: () => number | undefined
}

function noopSubscribe(): () => () => void {
  return () => {}
}

function noLatest(): undefined {
  return undefined
}

/** 从 turnOrder 末尾向前找最新有效卡回合：
 *  - 含非 message-ui 结果：置灰指针落在此回合
 *  - 纯 message-ui 提示回合（引擎拒绝）：状态未推进，跳过
 *  - 无 wuxia 结果：进行中（open）视为遮挡（GM 可能即将改状态，保持防并发锁定）；
 *    已结束视为未推进（如 judge 状态冲突报错、纯闲聊回合），跳过 */
function computeLatestCardTurn(timeline: any): number | undefined {
  const order = timeline?.turnOrder
  const turns = timeline?.turns
  if (!Array.isArray(order) || !turns || typeof turns.get !== 'function') return undefined
  for (let index = order.length - 1; index >= 0; index -= 1) {
    const turnNumber = order[index]
    const location = turns.get(turnNumber)
    const match = selectWuxiaResults({ turn: location })
    if (match) {
      if (match.results.some((result: any) => result?.界面 !== 'message-ui')) return turnNumber
      continue
    }
    if (location?.status === 'closed') continue
    return turnNumber
  }
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
    latestCardTurn: () => computeLatestCardTurn(source.getSnapshot()?.timeline),
  }
}

/** 当前会话最新回合号；无会话数据时为 undefined。 */
export function useTurnLatest(activity?: TurnActivity): number | undefined {
  return useSyncExternalStore(
    activity ? activity.subscribe : noopSubscribe,
    activity ? activity.latestTurn : noLatest,
  )
}

/** 当前会话最新有效卡回合号；无会话数据时为 undefined。 */
export function useLatestCardTurn(activity?: TurnActivity): number | undefined {
  return useSyncExternalStore(
    activity ? activity.subscribe : noopSubscribe,
    activity ? activity.latestCardTurn : noLatest,
  )
}
