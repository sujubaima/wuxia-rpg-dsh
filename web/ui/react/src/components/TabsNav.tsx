import { useGameStore } from '../store'
import type { TabKey } from '../types'

const TABS: { key: TabKey; label: string }[] = [
  { key: 'travel', label: '游历' },
  { key: 'bag', label: '物品' },
  { key: 'equip', label: '装备' },
  { key: 'wuxue', label: '武学' },
  { key: 'map', label: '地图' },
  { key: 'clue', label: '线索' },
  { key: 'char', label: '角色' },
  { key: 'save', label: '存档' },
]

export function TabsNav() {
  const activeTab = useGameStore(s => s.activeTab)
  const gateMode = useGameStore(s => s.gateMode)
  const setActiveTab = useGameStore(s => s.setActiveTab)
  if (gateMode) return <nav className="tabs" id="tabs"></nav>
  return (
    <nav className="tabs" id="tabs">
      {TABS.map(t => (
        <div
          key={t.key}
          className={'tab' + (t.key === activeTab ? ' active' : '')}
          onClick={() => setActiveTab(t.key)}
        >
          {t.label}
        </div>
      ))}
    </nav>
  )
}
