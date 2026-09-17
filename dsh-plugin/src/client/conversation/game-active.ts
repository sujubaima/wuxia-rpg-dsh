import { useSyncExternalStore } from 'react'
import { selectWuxiaResults } from './wuxia-data'

// 游戏进行中信号：会话 chat timeline 的任一回合含有 wuxia 引擎结果即视为已开局；
// 最新回合仍在进行（创建/载入等开场过程）同样视为进行中。
// timeline 由会话事件窗口重建，页面刷新后依然可靠（不依赖内存 store）。

export interface GameActivity {
  subscribe: (listener: () => void) => () => void
  isActive: () => boolean
}

function noopSubscribe(): () => void {
  return () => {}
}

function noActive(): boolean {
  return false
}

/** 从 uiConversation 会话绑定提炼游戏进行中信号源；绑定不可用时返回 undefined。 */
export function gameActivityOf(binding: any): GameActivity | undefined {
  let source: any
  try {
    source = binding?.target?.('chat')
  } catch { /* chat target 未注册 */ }
  if (!source || typeof source.subscribe !== 'function' || typeof source.getSnapshot !== 'function') {
    return undefined
  }
  return {
    subscribe: (listener: () => void) => source.subscribe(listener),
    isActive: () => {
      const turns = source.getSnapshot()?.timeline?.turns
      if (!turns || typeof turns.values !== 'function') return false
      for (const turn of turns.values()) {
        if (!turn) continue
        // 回合进行中（turn/start 后尚无 turn/end）：开场建号/读档等 GM 回合窗口
        if (turn.status === 'open') return true
        // selectWuxiaResults 的 owner 约定是 { turn: TurnLocation }
        if (selectWuxiaResults({ turn })) return true
      }
      return false
    },
  }
}

/** 当前会话是否已有 wuxia 引擎回合（游戏正式开始）。 */
export function useGameActive(activity?: GameActivity): boolean {
  return useSyncExternalStore(
    activity ? activity.subscribe : noopSubscribe,
    activity ? activity.isActive : noActive,
  )
}
