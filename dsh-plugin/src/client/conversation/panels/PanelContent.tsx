import type { PanelRequest } from '../panel-api'
import { BagPanel } from './BagPanel'
import { CharacterPanel } from './CharacterPanel'
import { CluePanel } from './CluePanel'
import { EquipPanel } from './EquipPanel'
import { LoadPanel } from './LoadPanel'
import { MapPanel } from './MapPanel'
import { SavePanel } from './SavePanel'
import { WuxuePanel } from './WuxuePanel'

export type PanelKind = 'save' | 'load' | 'bag' | 'equip' | 'wuxue' | 'map' | 'clue' | 'character'

type FeaturePanelKind = Exclude<PanelKind, 'save' | 'load'>

const PANEL_LABELS: Record<PanelKind, string> = {
  save: '存档',
  load: '读档',
  bag: '物品',
  equip: '装备',
  wuxue: '武学',
  map: '地图',
  clue: '线索',
  character: '角色',
}

export const PANEL_BUTTONS: { kind: FeaturePanelKind; label: string }[] = [
  { kind: 'bag', label: '物品' },
  { kind: 'equip', label: '装备' },
  { kind: 'wuxue', label: '武学' },
  { kind: 'map', label: '地图' },
  { kind: 'clue', label: '线索' },
  { kind: 'character', label: '角色' },
]

export function panelLabel(kind: PanelKind): string {
  return PANEL_LABELS[kind]
}

export function PanelContent({
  kind, slot, members, request, command, onLoadRequested,
}: {
  kind: PanelKind
  slot: number
  members: string[]
  request: PanelRequest
  command?: (line: string) => void
  onLoadRequested?: () => void
}) {
  const props = { slot, members, request }
  switch (kind) {
    case 'save': return <SavePanel {...props} />
    case 'load': return <LoadPanel {...props} command={command} onLoadRequested={onLoadRequested} />
    case 'bag': return <BagPanel {...props} />
    case 'equip': return <EquipPanel {...props} />
    case 'wuxue': return <WuxuePanel {...props} />
    case 'map': return <MapPanel {...props} />
    case 'clue': return <CluePanel {...props} />
    case 'character': return <CharacterPanel {...props} />
  }
}
