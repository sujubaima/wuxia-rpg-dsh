import { useGameStore } from '../../store'
import { rosterParse } from '../../lib/battleParse'
import { esc } from '../../lib/markdown'
import { Btn } from '../ui'
import type { BattleState, ParsedSkill } from '../../types'

function cdStr(s: ParsedSkill): string {
  const cd = s.冷却
  return cd && cd !== 0 && cd !== '无冷却' && cd !== '无' ? ' ｜ 冷却' + cd : ' ｜ 无冷却'
}

export function BattleConsole() {
  const lastBattle = useGameStore(s => s.lastBattle)
  const lastParse = useGameStore(s => s.lastParse)
  const bPick = useGameStore(s => s.bPick)
  const busy = useGameStore(s => s.busy)
  const replayLock = useGameStore(s => s.replayLock)
  const pick = useGameStore(s => s.pickBattleTarget)
  const battleAct = useGameStore(s => s.battleAct)
  const send = useGameStore(s => s.send)
  const setBPick = useGameStore(s => s.setBPick)

  const st = (lastBattle?.战局状态 as BattleState) || {}
  const ended = !!st.状态 && st.状态 !== '进行中'
  const mine = lastParse?.actor ? rosterParse(st.我方).some(r => r.name === lastParse.actor) : false
  const usable = !ended && mine && !busy && !replayLock
  const skills = lastParse?.skills || []
  const items = lastParse?.items || []
  const canFlee = lastBattle?.允许逃跑 !== false

  let turn: React.ReactNode
  let watch = ''
  if (ended) turn = '—— 战局已终'
  else if (!lastParse || !lastParse.actor) { turn = '◌ 战局推演中…'; watch = '（纯 AI 回合，或尚未轮到玩家）' }
  else { turn = <>▶ 轮到 <b>{esc(lastParse.actor)}</b></>; watch = busy ? 'GM 正在结算…' : '' }

  return (
    <section className={'bconsole' + (usable ? '' : ' locked')} id="bConsole">
      <div className="ckv"><span className="turn">{turn}</span><span className="watch">{watch}</span></div>
      <div className="cgrid" id="bGrid">
        <div className="cgroup">
          <span className="g-label">武学（战斗携带 ≤4）</span>
          <div className="g-cards">
            {[0, 1, 2, 3].map(i => {
              const s = skills[i]
              if (!s) return <div className="skcard empty" key={i}>（空槽）</div>
              const picked = bPick?.kind === 'skill' && bPick.name === s.名称
              const reasons = s.flags
                ? s.flags.filter(f => f !== '可用')
                : [s.冷却中 && `冷却中(剩${s.冷却剩余 || 0}回合)`, s.内力不足 && '内力不足', s.武器不符 && '武器不符'].filter(Boolean)
              return (
                <div className={'skcard' + (!s.可用 ? ' disabled' : '') + (picked ? ' picked' : '')} key={i}
                  onClick={s.可用 ? () => pick('skill', s) : undefined}>
                  <div className="sn">◆ {esc(s.名称)}</div>
                  <div className="sp">{esc(s.类型)} ｜ {esc(s.范围 || '敌方单体')}</div>
                  <div className="sp">威力{esc(String(s.威力))} ｜ 内力{esc(String(s.内力))}{esc(cdStr(s))}</div>
                  {!s.可用 && <div className="cdnote">{reasons.join('、')}</div>}
                </div>
              )
            })}
          </div>
        </div>
        <div className="cdiv"></div>
        <div className="cgroup">
          <span className="g-label">战斗携带物品</span>
          <div className="g-cards">
            {[0, 1, 2, 3].map(i => {
              const it = items[i]
              if (!it) return <div className="skcard empty" key={i}>（空槽）</div>
              const picked = bPick?.kind === 'item' && bPick.name === it.名称
              return (
                <div className={'skcard' + (picked ? ' picked' : '')} key={i} onClick={() => pick('item', it)}>
                  <div className="sn">▤ {esc(it.名称)} ×{it.数量}</div>
                  <div className="sp">{esc(it.效果 || '')}</div>
                  <div className="sp">{esc(it.方向 || '')}</div>
                </div>
              )
            })}
          </div>
        </div>
        <div className="cdiv"></div>
        <div className="fbtns">
          <button className="fbtn" onClick={() => battleAct({ 类型: '战斗-休息' })}>休息（回内力10%）</button>
          <button className="fbtn" disabled={!canFlee} title={canFlee ? '' : '此战不容脱身'} onClick={() => battleAct({ 类型: '战斗-逃跑' })}>逃跑</button>
          <button className="fbtn danger" onClick={() => { if (confirm('确定认输？我方将判负。')) battleAct({ 类型: '战斗-认输' }) }}>认输</button>
          <button className="fbtn" onClick={() => { if (!busy) void send('查看人物信息') }}>查看人物</button>
          {bPick && <button className="fbtn" onClick={() => setBPick(null)}>取消选择</button>}
        </div>
      </div>
    </section>
  )
}
