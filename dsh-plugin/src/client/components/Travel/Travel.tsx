import { useGameStore } from '../../store'
import { Headband } from './Headband'
import { WaitPanel } from './WaitPanel'
import { Stage } from './Stage'
import { TravelLog } from './TravelLog'
import { Composer } from './Composer'

export function Travel() {
  const steps = useGameStore(s => s.steps)
  const stage = useGameStore(s => s.stage)
  const stageExpanded = useGameStore(s => s.stageExpanded)
  const awaiting = !!stage && stage.hasContent && !stageExpanded
  return (
    <div id="panelTravel" className={steps > 0 ? 'working' : ''}>
      <Headband />
      <WaitPanel />
      <Stage />
      {!awaiting && <TravelLog />}
      {!awaiting && <Composer />}
    </div>
  )
}
