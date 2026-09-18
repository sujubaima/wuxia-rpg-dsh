import { useEffect, useState } from 'react'
import { Fragment, jsx, jsxs } from 'react/jsx-runtime'
import { BattleCard } from './battle/BattleCard'
import type { BattleRequest } from './battle-api'
import type { DeleteRequest } from './delete-api'
import { ExplorationBattleCard } from './ExplorationBattleCard'
import { ExplorationCard } from './ExplorationCard'
import { toastWuxiaMessage } from './message-toast'
import type { PanelRequest } from './panel-api'
import { TitleCard } from './TitleCard'
import { useLatestCardTurn, useTurnLatest, type TurnActivity } from './turn-activity'
import { selectWuxiaResults } from './wuxia-data'

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

export function WuxiaTurnTail({ turn, command, setDraft, panelRequest, battleRequest, deleteRequest, turnActivity }: {
  turn?: { turn?: number; data?: unknown }
  command?: (line: string) => void
  setDraft?: (text: string) => void
  panelRequest?: PanelRequest
  battleRequest?: BattleRequest
  deleteRequest?: DeleteRequest
  turnActivity?: TurnActivity
}) {
  // hook 须在早退之前调用，保持 hook 顺序稳定
  const latestTurn = useTurnLatest(turnActivity)
  const latestCardTurn = useLatestCardTurn(turnActivity)
  // 0.1.6-alpha.2 起 turnTail 为 list 槽：组件收 owner.turn（TurnLocation），自行派生数据
  const matched = turn ? selectWuxiaResults({ turn }) : null
  // message-ui 不渲染卡片，提示改为 toast；仅本回合即会话最新回合时弹，历史回溯不重复
  useEffect(() => {
    if (!matched || matched.turn === undefined || matched.turn !== latestTurn) return
    for (const item of matched.results) {
      if (item?.界面 === 'message-ui') toastWuxiaMessage(item)
    }
  })
  if (!matched || !matched.results || matched.results.length === 0) return null
  // 本回合取最后一张有效卡片；纯提示回合不出卡片
  const cardResults = matched.results.filter((item: any) => item?.界面 !== 'message-ui')
  if (cardResults.length === 0) return null
  // 纯 message-ui 提示回合不推进状态：置灰指针跳过它们，上一轮卡片保持可用
  const stale = matched.turn !== undefined && latestCardTurn !== undefined && matched.turn !== latestCardTurn
  const result = cardResults[cardResults.length - 1]
  const view = result?.界面 ?? '?'
  const saves = result?.存档列表 as any[] | undefined

  if (view === 'title-ui') return jsx(TitleCard, {
    saves,
    nextSlot: result?.next_slot as number | undefined,
    version: result?.版本 as string | undefined,
    command,
    deleteRequest,
    locked: stale,
  })
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
