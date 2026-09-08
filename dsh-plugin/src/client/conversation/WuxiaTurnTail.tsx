import { useState } from 'react'
import { Fragment, jsx, jsxs } from 'react/jsx-runtime'
import { BattleCard } from './battle/BattleCard'
import type { BattleRequest } from './battle-api'
import type { DeleteRequest } from './delete-api'
import { ExplorationBattleCard } from './ExplorationBattleCard'
import { ExplorationCard } from './ExplorationCard'
import type { PanelRequest } from './panel-api'
import { TitleCard } from './TitleCard'
import { useTurnLatest, type TurnActivity } from './turn-activity'

function ExplorationBattleStack({ data, battleRequest, locked }: {
  data: Record<string, any>
  battleRequest?: BattleRequest
  locked?: boolean
}) {
  const [battle, setBattle] = useState<Record<string, any> | null>(null)

  return jsxs(Fragment, {
    children: [
      jsx(ExplorationBattleCard, {
        data,
        battleRequest,
        locked,
        onStarted: setBattle,
      }),
      battle ? jsx(BattleCard, { initialData: battle, battleRequest, locked }) : null,
    ],
  })
}

export function WuxiaTurnTail({ matched, command, setDraft, panelRequest, battleRequest, deleteRequest, turnActivity }: {
  matched?: { turn?: number; results?: readonly any[] }
  command?: (line: string) => void
  setDraft?: (text: string) => void
  panelRequest?: PanelRequest
  battleRequest?: BattleRequest
  deleteRequest?: DeleteRequest
  turnActivity?: TurnActivity
}) {
  // hook 须在早退之前调用，保持 hook 顺序稳定
  const latestTurn = useTurnLatest(turnActivity)
  if (!matched || !matched.results || matched.results.length === 0) return null
  // 一旦有新回合开始，本卡即为过时快照，永久锁定、不随回合结束恢复
  const stale = matched.turn !== undefined && latestTurn !== undefined && matched.turn !== latestTurn
  const result = matched.results[matched.results.length - 1]
  const view = result?.界面 ?? '?'
  const saves = result?.存档列表 as any[] | undefined

  if (view === 'title-ui') return jsx(TitleCard, { saves, command, deleteRequest, locked: stale })
  if (view === 'exploration-ui') {
    return jsx(ExplorationCard, { data: result, setDraft, panelRequest, locked: stale })
  }
  if (view === 'exploration-battle-ui') {
    return jsx(ExplorationBattleStack, { data: result, battleRequest, locked: stale })
  }
  if (view === 'battle-ui' || view === 'battle-end-ui') {
    return jsx(BattleCard, { initialData: result, battleRequest, locked: stale })
  }

  return jsxs('div', {
    style: {
      padding: '12px 16px', margin: '8px 0 4px', borderRadius: 10,
      border: '1px solid #2a2218', background: '#221c16',
      color: '#e8dcc4', fontSize: 13, lineHeight: 1.6,
    },
    children: [
      jsx('div', {
        style: { fontWeight: 600, marginBottom: 6, color: '#c8a456' },
        children: `🎮 ${view}`,
      }),
      saves && saves.length > 0 ? jsxs('div', {
        style: { color: '#9a8c6e', fontSize: 12 },
        children: [
          jsx('div', { style: { marginBottom: 4 }, children: `存档 ${saves.length} 个：` }),
          ...saves.slice(0, 8).map((save: any, index: number) =>
            jsx('div', {
              style: { paddingLeft: 12 },
              children: `slot ${save.slot} · ${save.角色名 || '（无名）'} · 最近 ${save.最近存档 || '—'}`,
            }, index),
          ),
        ],
      }) : null,
    ],
  })
}
