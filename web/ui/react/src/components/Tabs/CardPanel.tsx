import type { ReactNode } from 'react'
import { useGameStore } from '../../store'
import { BagView } from './BagView'
import { EquipView } from './EquipView'
import { WuxueView } from './WuxueView'
import { MapView } from './MapView'
import { ClueView } from './ClueView'
import { CharView } from './CharView'
import { SaveView } from './SaveView'

export function CardPanel() {
  const activeTab = useGameStore(s => s.activeTab)
  switch (activeTab) {
    case 'bag': return <BagView />
    case 'equip': return <EquipView />
    case 'wuxue': return <WuxueView />
    case 'map': return <MapView />
    case 'clue': return <ClueView />
    case 'char': return <CharView />
    case 'save': return <SaveView />
    default: return <div className="ph">该面板尚未实现。</div>
  }
}

export function CardShell({ title, desc, children }: { title: string; desc?: string; children: ReactNode }) {
  return (
    <div>
      {desc && <div className="cdesc">{desc}</div>}
      <div className="card">
        <h3>{title}</h3>
        {children}
      </div>
    </div>
  )
}

/** 数据未就绪时的加载占位：只显标题 + "读取中…"，不渲染任何功能控件，避免空壳误导。 */
export function LoadingCard({ title }: { title: string }) {
  return (
    <div>
      <div className="card">
        <h3>{title}</h3>
        <div className="ph">读取中…</div>
      </div>
    </div>
  )
}

export function DumpJson({ data }: { data: unknown }) {
  return <pre className="jsonout">{JSON.stringify(data, null, 2).slice(0, 6000)}</pre>
}
