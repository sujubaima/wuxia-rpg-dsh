import { useGameStore } from '../../store'
import { fmtMoney } from '../../lib/format'

export function PartySidebar() {
  const gateMode = useGameStore(s => s.gateMode)
  const inBattle = useGameStore(s => s.inBattle)
  const party = useGameStore(s => s.party)
  const currentSlot = useGameStore(s => s.currentSlot)
  const selectedMember = useGameStore(s => s.selectedMember)
  const setSelectedMember = useGameStore(s => s.setSelectedMember)
  if (gateMode) return <aside className="party"></aside>

  const members = party?.队伍状态 || []
  const memberSlots = Array.from({ length: 4 }, (_, index) => members[index] ?? null)
  const names = members.slice(0, 4).map(m => m.名称 || '')
  const selName = selectedMember && names.includes(selectedMember) ? selectedMember : names[0] || null

  return (
    <aside className="party">
      <div className="phead">
        当 前 队 伍<span className="slot-chip">slot {currentSlot || '—'}</span>
      </div>
      <div className="resrow">
        <div className="res">体力<b>{party?.体力 == null ? '—' : party.体力}</b></div>
        <div className="res">金钱<b>{party?.金钱 == null ? '—' : fmtMoney(party.金钱)}</b></div>
      </div>
      <div id="pmembers">
        {memberSlots.map((m, index) => {
          if (!m) {
            return (
              <div key={`empty:${index}`} className="pmember empty">
                <div className="top"><span className="nm">（空位）</span></div>
                <div className="bars">
                  <div className="bar hp"></div>
                  <div className="bar mp"></div>
                </div>
              </div>
            )
          }
          const name = m.名称 || ''
          const hp = Math.max(0, Math.min(100, ((m.气血 || 0) / (m.气血上限 || 1)) * 100))
          const mp = Math.max(0, Math.min(100, ((m.内力 || 0) / (m.内力上限 || 1)) * 100))
          return (
            <div
              key={`${name}:${index}`}
              className={'pmember' + (name === selName ? ' sel' : '')}
              onClick={() => { if (!inBattle) setSelectedMember(name) }}
            >
              <div className="top"><span className="nm">{name}</span></div>
              <div className="bars">
                <div className={'bar hp' + (hp < 35 ? ' low' : '')}>
                  <i style={{ width: hp + '%' }}></i>
                  <span>气血 {m.气血}/{m.气血上限}</span>
                </div>
                <div className="bar mp">
                  <i style={{ width: mp + '%' }}></i>
                  <span>内力 {m.内力}/{m.内力上限}</span>
                </div>
              </div>
            </div>
          )
        })}
      </div>
    </aside>
  )
}
