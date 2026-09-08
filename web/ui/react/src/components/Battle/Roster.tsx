import { useGameStore } from '../../store'
import { rosterParse } from '../../lib/battleParse'
import { registerCard } from './battleRefs'
import { esc } from '../../lib/markdown'
import type { BattleState, ParsedAction } from '../../types'

function Bars({ hp, mp }: { hp: string; mp: string }) {
  let hpBar: React.ReactNode = <div className="bar hp"><i style={{ width: '100%' }}></i><span>气血 —</span></div>
  if (hp && /\//.test(hp)) {
    const [a, mm] = hp.split('/')
    const an = +a || 0, mmn = +mm || 1
    const p = Math.max(0, Math.min(100, (an / mmn) * 100))
    hpBar = (
      <div className={'bar hp' + (p < 35 ? ' low' : '')}>
        <i style={{ width: p + '%' }}></i><span>气血 {an}/{mmn}</span>
      </div>
    )
  }
  let mpBar: React.ReactNode = null
  if (mp && /\//.test(mp)) {
    const [a, b] = mp.split('/')
    const an = +a || 0, bn = +b || 1
    const p = Math.max(0, Math.min(100, (an / bn) * 100))
    mpBar = <div className="bar mp"><i style={{ width: p + '%' }}></i><span>内力 {an}/{bn}</span></div>
  }
  return <div className="bars">{hpBar}{mpBar}</div>
}

function Side({ list, side, parse, bPick, resolve }: {
  list: string[]; side: 'enemy' | 'ally'; parse: ParsedAction | null
  bPick: { dir: string; noSelf: boolean } | null
  resolve: (name: string) => void
}) {
  return (
    <>
      {rosterParse(list).map(r => {
        const tbl = parse?.table?.[r.name]
        const dead = /败阵/.test(r.tag) || tbl?.状态列 === '败阵'
        const fled = /逃走/.test(r.tag) || tbl?.状态列 === '逃走'
        const acting = parse?.actor === r.name && !dead && !fled
        const targetable = !!bPick && !dead && !fled && !(bPick.noSelf && acting) &&
          ((bPick.dir === '敌方' && side === 'enemy') || (bPick.dir === '我方' && side === 'ally'))
        const states = tbl?.状态 && tbl.状态 !== '无' ? tbl.状态.split('、') : []
        const cds = tbl?.冷却 && tbl.冷却 !== '无' ? tbl.冷却.split('、') : []
        return (
          <div
            key={r.name}
            id={'bc_' + r.name}
            ref={el => registerCard(r.name, el)}
            className={'bcard ' + side + (dead ? ' dead' : '') + (fled ? ' dead fled' : '') + (acting ? ' acting' : '') + (targetable ? ' targetable' : '')}
            onClick={targetable ? () => resolve(r.name) : undefined}
          >
            <div className="bnm">
              <span>{esc(r.name)}</span>
              <span className="crown">{esc(r.tag && r.tag !== '战斗中' ? r.tag : '')}</span>
            </div>
            <Bars hp={tbl?.气血 || ''} mp={tbl?.内力 || ''} />
            <div className="sts">
              {states.map((s, i) => <span className="stg" key={i}>{s}</span>)}
              {cds.map((s, i) => <span className="stg cd" key={'c' + i}>{s}</span>)}
            </div>
          </div>
        )
      })}
    </>
  )
}

export function Roster() {
  const lastBattle = useGameStore(s => s.lastBattle)
  const lastParse = useGameStore(s => s.lastParse)
  const bPick = useGameStore(s => s.bPick)
  const resolve = useGameStore(s => s.resolveBattleAction)
  const st = (lastBattle?.战局状态 as BattleState) || {}
  return (
    <>
      <div className="bside-label enemy">敌 方</div>
      <div className="formation" id="bEnemy">
        <Side list={st.敌方 || []} side="enemy" parse={lastParse} bPick={bPick} resolve={resolve} />
      </div>
      <div className="bspacer"></div>
      <div className="formation" id="bAlly">
        <Side list={st.我方 || []} side="ally" parse={lastParse} bPick={bPick} resolve={resolve} />
      </div>
      <div className="bside-label ally">我 方</div>
    </>
  )
}
