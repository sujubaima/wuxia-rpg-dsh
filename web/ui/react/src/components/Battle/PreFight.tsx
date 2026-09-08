import { useGameStore } from '../../store'

export function PreFight() {
  const d = useGameStore(s => s.preFight)
  const stageExpanded = useGameStore(s => s.stageExpanded)
  const startBattle = useGameStore(s => s.startBattle)
  if (!d || !stageExpanded) return null
  const opts = (d.操控选项 as string[])?.length ? (d.操控选项 as string[]) : ['开战']
  return (
    <div id="preFight" className="bmask show">
      <div className="endcard">
        <div className="verdict">短 兵 相 接</div>
        <div className="pf-line"><b>我方</b>　<span className="pf-ally">{(d.我方 as string[])?.join('、') || '—'}</span></div>
        <div className="pf-line"><span className="en">敌方</span>　<span className="pf-foe">{(d.敌方 as string[])?.join('、') || '—'}</span></div>
        <div className="vsub">选择操控方式后开战</div>
        <div className="pfbtns">
          {opts.map(opt => <button key={opt} onClick={() => startBattle(d, opt)}>{opt}</button>)}
        </div>
      </div>
    </div>
  )
}
