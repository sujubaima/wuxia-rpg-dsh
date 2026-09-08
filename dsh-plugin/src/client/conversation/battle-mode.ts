import { create } from 'zustand'

// 战斗模式：进入 battle-ui / battle-end-ui 期间隐藏队伍状态浮窗；
// 回到 exploration-ui 或玩家在 battle-end-ui 点击结算提交后恢复。
// WuxiaTurnTail 按当前 turn 的 view 写入（历史 turn 先执行、最新 turn 最后写入），
// BattleCard 在 submitted 时调用 clearBattleMode 提前恢复。
interface BattleModeState {
  active: boolean
  setActive: (value: boolean) => void
  clear: () => void
}

export const useBattleMode = create<BattleModeState>((set) => ({
  active: false,
  setActive: (value) => set({ active: value }),
  clear: () => set({ active: false }),
}))
