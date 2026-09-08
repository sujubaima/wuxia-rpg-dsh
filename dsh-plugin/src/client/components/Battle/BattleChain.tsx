import { useGameStore } from '../../store'
import { rosterParse } from '../../lib/battleParse'
import { esc } from '../../lib/markdown'
import { battleChainSeq } from './useBattleReplay'
import type { BattleState } from '../../types'

export function BattleChain() {
  const lastBattle = useGameStore(s => s.lastBattle)
  const lastParse = useGameStore(s => s.lastParse)
  const lastOrder = useGameStore(s => s.lastOrder)
  const replayChain = useGameStore(s => s.replayChain)
  const st = (lastBattle?.战局状态 as BattleState) || {}
  const ally = new Set(rosterParse(st.我方).map(r => r.name))
  const tags: Record<string, string> = {}
  for (const r of rosterParse(st.我方).concat(rosterParse(st.敌方))) tags[r.name] = r.tag
  // 回放中用逐帧顺序；否则用终态静态预告
  const seq = (replayChain && replayChain.length ? replayChain : battleChainSeq({ lastParse, lastOrder }, st)).slice(0, 7)
  const firstAlive = seq.findIndex(nm => !/败阵|逃走/.test(tags[nm] || ''))
  let num = 0
  return (
    <div className="chain" id="bChain">
      <span className="clabel">行 动 预 告</span>
      {seq.map((nm, i) => {
        const dead = /败阵|逃走/.test(tags[nm] || '')
        const isAlly = ally.has(nm)
        let content: React.ReactNode
        if (dead) content = <><i>✕</i>{esc(nm)}</>
        else { num++; content = <><i>{num}</i>{esc(nm)}</> }
        return (
          <span key={i} style={{ display: 'contents' }}>
            <div className={'node ' + (isAlly ? 'ally' : 'enemy') + (dead ? ' dead' : '') + (i === firstAlive ? ' now' : '')}>
              {content}
            </div>
            {i < seq.length - 1 && <span className="arrow">→</span>}
          </span>
        )
      })}
    </div>
  )
}
