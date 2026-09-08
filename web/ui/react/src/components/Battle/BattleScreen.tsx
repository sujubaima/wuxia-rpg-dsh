import { useGameStore } from '../../store'
import { useBattleReplay } from './useBattleReplay'
import { Roster } from './Roster'
import { BattleChain } from './BattleChain'
import { BattleConsole } from './BattleConsole'
import { BattleEndDialog } from './BattleEndDialog'
import { PreFight } from './PreFight'

export function BattleScreen() {
  const inBattle = useGameStore(s => s.inBattle)
  const bEnded = useGameStore(s => s.bEnded)
  const lastBattle = useGameStore(s => s.lastBattle)
  const exitBattle = useGameStore(s => s.exitBattle)
  const addSysLine = useGameStore(s => s.addSysLine)
  useBattleReplay()

  if (!inBattle) return null
  const st = (lastBattle?.战局状态 as any) || {}
  const ended = !!st.状态 && st.状态 !== '进行中'
  const stateColor = !ended ? 'var(--ok)' : /我方胜|敌方认输/.test(st.状态 || '') ? 'var(--accent)' : 'var(--danger)'

  return (
    <div id="battleScreen">
      <div className="bhead">
        <span className="bname"><em>⚔</em><span id="bName">遭遇战</span></span>
        <span className="tag" id="bRound">{st.回合数 != null ? `第 ${st.回合数} 回合` : ''}</span>
        <span className="tag" id="bState" style={{ color: stateColor }}>{st.状态 || ''}</span>
        <div className="spacer"></div>
        <button id="bExit" onClick={() => {
          if (inBattle && !bEnded) { addSysLine('战斗进行中——打完方可离场'); return }
          exitBattle()
        }}>退出战斗画面</button>
      </div>
      <BattleChain />
      <div className="bbody">
        <section className="bfield">
          <Roster />
          <BattleConsole />
        </section>
      </div>
      <BattleEndDialog />
      <PreFight />
    </div>
  )
}
