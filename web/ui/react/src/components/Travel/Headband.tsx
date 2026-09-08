import { useGameStore } from '../../store'

const STEP_LABELS = ['结算', '判盘', '运笔']

export function Headband() {
  const hb = useGameStore(s => s.headband)
  const steps = useGameStore(s => s.steps)
  return (
    <div id="headband">
      <div className="hb-loc">
        <div className="region">{hb.region}</div>
        <div className="scene">{hb.scene}</div>
      </div>
      <div className="hb-spacer"></div>
      <div className="hb-steps">
        {STEP_LABELS.map((label, i) => (
          <span key={i} className={'stp' + (steps === i + 1 ? ' active' : '')}>{label}</span>
        ))}
      </div>
      <div className="hb-save">{hb.saveRemain || ''}</div>
      <div className="hb-time">
        <div className="clock">
          <span className="icon">{hb.icon}</span>
          <span>{hb.clock}</span>
        </div>
        <div className="cal">{hb.cal}</div>
      </div>
    </div>
  )
}
