import { useEffect, useRef, useState } from 'react'
import { jsx, jsxs } from 'react/jsx-runtime'
import {
  CardInteractionModal, type CardInteractionKind,
} from './interactions/CardInteractionModal'
import type { PanelRequest } from './panel-api'
import { applyPartyState, useParty } from './party-store'
import { engineError } from './panels/PanelPrimitives'
import {
  BORDER_COLOR, CARD_STYLE, DIM_COLOR, ExplorationSummary, TITLE_COLOR, formatPosition,
} from './ExplorationSummary'
const DIRECTIONS = [['西北', '北', '东北'], ['西', '', '东'], ['西南', '南', '东南']]

interface InteractionState {
  kind: CardInteractionKind
  data?: any
  loading: boolean
  busy: boolean
  error: string
}

function interactionKind(command: string): CardInteractionKind | null {
  if (command === '购买') return 'buy'
  if (command === '出售' || command === '售卖') return 'sell'
  if (command === '远行（舟车）') return 'travel'
  if (command === '投宿' || command === '休息') return 'inn'
  return null
}

function openingAction(
  kind: CardInteractionKind,
  subject: string,
  merchant: boolean,
): Record<string, unknown> {
  switch (kind) {
    case 'buy': return { 类型: '购买', 卖家: subject, 商人: merchant }
    case 'sell': return { 类型: '出售', 买家: subject, 商人: merchant }
    case 'travel': return { 类型: '远行（舟车）' }
    case 'inn': return { 类型: '休息', 免费: false }
  }
}

const INTERACTION_VIEW: Record<CardInteractionKind, string> = {
  buy: 'trade-buy-ui',
  sell: 'trade-sell-ui',
  travel: 'travel-ui',
  inn: 'inn-ui',
}

/** exploration-ui：仅渲染游历面板中间舞台，不包含两侧栏。 */
export function ExplorationCard({ data, setDraft, panelRequest, locked }: {
  data: any
  setDraft?: (text: string) => void
  panelRequest?: PanelRequest
  /** 所属回合已被新回合取代：过时快照，控件永久禁用、仅供回顾 */
  locked?: boolean
}) {
  const [viewData, setViewData] = useState(data)
  const [interaction, setInteraction] = useState<InteractionState | null>(null)
  const requestId = useRef(0)

  useEffect(() => {
    requestId.current += 1
    setViewData(data)
    setInteraction(null)
  }, [data])

  // 回合已被新回合取代时关掉卡内交互弹窗：卡片状态已过时
  useEffect(() => {
    if (locked) {
      requestId.current += 1
      setInteraction(null)
    }
  }, [locked])

  const resolveSlot = (): number | null => {
    const fromCard = Number(viewData?.槽位)
    if (Number.isInteger(fromCard) && fromCard > 0) return fromCard
    return useParty.getState().slot
  }

  const openInteraction = async (kind: CardInteractionKind, subject: string) => {
    if (!panelRequest || locked) return
    const slot = resolveSlot()
    if (slot == null) {
      setInteraction({ kind, loading: false, busy: false, error: '当前游历卡缺少有效存档槽位' })
      return
    }
    const merchant = viewData?.当前场景类型 === '店铺' || viewData?.当前场景类型 === '客栈'
    const currentRequest = ++requestId.current
    setInteraction({ kind, loading: true, busy: false, error: '' })
    try {
      const response = await panelRequest(slot, [openingAction(kind, subject, merchant)])
      if (currentRequest !== requestId.current) return
      applyPartyState(response.state)
      const result = response.results[0]
      const error = engineError(result)
      if (error) throw new Error(error)
      if (result?.界面 !== INTERACTION_VIEW[kind]) {
        throw new Error(`engine 未返回 ${INTERACTION_VIEW[kind]} 交互界面`)
      }
      setInteraction({ kind, data: result, loading: false, busy: false, error: '' })
    } catch (caught) {
      if (currentRequest !== requestId.current) return
      setInteraction({
        kind, loading: false, busy: false,
        error: caught instanceof Error ? caught.message : String(caught),
      })
    }
  }

  const submitInteraction = async (action: Record<string, unknown>) => {
    if (!panelRequest || !interaction) return
    const slot = resolveSlot()
    if (slot == null) {
      setInteraction(value => value ? { ...value, error: '当前游历卡缺少有效存档槽位' } : value)
      return
    }
    const currentRequest = ++requestId.current
    setInteraction(value => value ? { ...value, busy: true, error: '' } : value)
    try {
      const response = await panelRequest(slot, [action])
      if (currentRequest !== requestId.current) return
      applyPartyState(response.state)
      const settled = response.results[0]
      const error = engineError(settled)
      if (error) throw new Error(error)
      if (response.followup) {
        setInteraction(null)
        return
      }
      const result = response.view ?? settled
      const viewError = engineError(result)
      if (viewError) throw new Error(viewError)
      if (result?.界面 !== 'exploration-ui') {
        throw new Error(`engine 结算后返回了 ${String(result?.界面 || '未知界面')}`)
      }
      applyPartyState(result)
      setViewData(result)
      setInteraction(null)
    } catch (caught) {
      if (currentRequest !== requestId.current) return
      setInteraction(value => value ? {
        ...value, busy: false,
        error: caught instanceof Error ? caught.message : String(caught),
      } : value)
    }
  }

  const closeInteraction = () => {
    requestId.current += 1
    setInteraction(null)
  }

  const position = formatPosition(viewData.当前位置)
  const elements = ((viewData.场景要素 as any[]) || []).map((feature: any) => {
    if (feature && typeof feature === 'object') {
      const raw = feature.特殊指令
      const commands = Array.isArray(raw)
        ? raw.filter((c: any) => c && typeof c === 'object' && typeof c.名称 === 'string' && c.名称.trim() && typeof c.可用 === 'boolean')
            .map((c: any) => ({ 名称: String(c.名称).trim(), 可用: Boolean(c.可用) }))
        : null
      return {
        主体: feature.主体 || '',
        描写: feature.描写 || '',
        特殊指令: commands && commands.length ? commands : null,
      }
    }
    return { 主体: String(feature || ''), 描写: '', 特殊指令: null }
  }).filter(feature => feature.主体)
  const exits = ((viewData.相邻出口 as any[]) || []).map((exit: any) => ({ 方位: exit.方位, 邻场景: exit.邻场景 }))
  const exitMap: Record<string, string> = {}
  for (const exit of exits) if (exit.方位) exitMap[exit.方位] = exit.邻场景
  const currentName = position ? position.split(' · ').pop() : ''

  return jsxs('div', {
    style: {
      ...CARD_STYLE,
      position: 'relative',
      ...(interaction ? { minHeight: 420 } : {}),
    },
    children: [
      jsx(ExplorationSummary, { data: viewData }),
      (elements.length > 0 || exits.length > 0) ? jsxs('div', {
        style: {
          borderTop: '1px dashed ' + BORDER_COLOR, paddingTop: 8, marginTop: 4,
          opacity: locked ? 0.55 : 1,
          pointerEvents: locked ? 'none' : 'auto',
          transition: 'opacity 150ms ease',
        },
        title: locked ? '回合已推进，此卡仅供回顾' : undefined,
        children: [
          elements.length > 0 ? jsxs('div', {
            children: [
              jsx('div', {
                style: { fontSize: 12, color: DIM_COLOR, letterSpacing: 3, marginBottom: 4 },
                children: '周 围 情 况',
              }),
              ...elements.map((feature, index) => jsxs('div', {
                style: {
                  display: 'flex', alignItems: 'baseline', gap: 6, padding: '2px 5px',
                  borderRadius: 4, background: 'transparent',
                  cursor: setDraft ? 'pointer' : 'default',
                  transition: 'background 120ms ease, box-shadow 120ms ease',
                },
                title: setDraft ? '填入交谈指令' : undefined,
                onMouseEnter: setDraft ? (event: any) => {
                  event.currentTarget.style.background = 'rgba(200,164,86,0.10)'
                  event.currentTarget.style.boxShadow = 'inset 0 0 0 1px rgba(177,135,59,0.42)'
                } : undefined,
                onMouseLeave: setDraft ? (event: any) => {
                  event.currentTarget.style.background = 'transparent'
                  event.currentTarget.style.boxShadow = 'none'
                } : undefined,
                onClick: setDraft ? () => setDraft('与' + feature.主体 + '交谈') : undefined,
                children: [
                  jsx('span', { style: { color: TITLE_COLOR }, children: '◆' }),
                  jsx('span', { children: feature.描写 ? `${feature.主体}（${feature.描写}）` : feature.主体 }),
                  feature.特殊指令 ? jsx('span', {
                    style: { marginLeft: 6, display: 'inline-flex', gap: 4 },
                    children: feature.特殊指令.map((command: { 名称: string; 可用: boolean }) => {
                      const kind = interactionKind(command.名称)
                      const direct = Boolean(kind && panelRequest)
                      const clickable = command.可用 && (direct || Boolean(setDraft))
                      return jsx('span', {
                        style: {
                          fontSize: 11, padding: '0 6px',
                          border: '1px solid rgba(138,106,42,0.5)', borderRadius: 3,
                          color: command.可用 ? TITLE_COLOR : '#5a4d3a',
                          background: 'transparent',
                          opacity: command.可用 ? 1 : 0.45,
                          cursor: clickable ? 'pointer' : 'default',
                          transition: 'color 120ms ease, background 120ms ease, border-color 120ms ease, box-shadow 120ms ease',
                        },
                        title: !command.可用 ? '当前不可用' : direct ? '打开卡内交互' : setDraft ? '填入指令' : undefined,
                        onMouseEnter: clickable ? (event: any) => {
                          event.currentTarget.style.color = '#f0cf82'
                          event.currentTarget.style.background = '#3a2b17'
                          event.currentTarget.style.borderColor = '#b1873b'
                          event.currentTarget.style.boxShadow = '0 0 6px rgba(200,164,86,0.28)'
                        } : undefined,
                        onMouseLeave: clickable ? (event: any) => {
                          event.currentTarget.style.color = TITLE_COLOR
                          event.currentTarget.style.background = 'transparent'
                          event.currentTarget.style.borderColor = 'rgba(138,106,42,0.5)'
                          event.currentTarget.style.boxShadow = 'none'
                        } : undefined,
                        onClick: clickable ? (event: any) => {
                          event.stopPropagation()
                          if (kind && panelRequest) {
                            void openInteraction(kind, feature.主体)
                          } else {
                            setDraft?.(command.名称)
                          }
                        } : undefined,
                        children: command.名称 === '远行（舟车）' ? '远行' : command.名称,
                      }, command.名称)
                    }),
                  }) : null,
                ],
              }, index)),
            ],
          }) : null,
          exits.length > 0 ? jsxs('div', {
            style: { marginTop: 8 },
            children: [
              jsx('div', {
                style: { fontSize: 12, color: DIM_COLOR, letterSpacing: 3, marginBottom: 4 },
                children: '出 口',
              }),
              jsx('div', {
                style: { display: 'grid', gridTemplateColumns: 'repeat(3, 1fr)', gap: 4, maxWidth: 320 },
                children: DIRECTIONS.flat().map((direction, index) => {
                  if (direction === '') {
                    return jsx('div', {
                      key: index,
                      style: { padding: '4px 6px', textAlign: 'center', fontSize: 12, color: TITLE_COLOR, border: '1px solid rgba(138,106,42,0.5)', borderRadius: 4 },
                      children: `◈ ${currentName}`,
                    })
                  }
                  const target = exitMap[direction]
                  return jsx('div', {
                    key: index,
                    style: {
                      padding: '4px 6px', fontSize: 12, borderRadius: 4,
                      border: '1px solid ' + (target ? 'rgba(138,106,42,0.4)' : BORDER_COLOR),
                      color: target ? '#e8dcc4' : DIM_COLOR,
                      background: target ? 'rgba(200,164,86,0.05)' : 'transparent',
                      cursor: setDraft && target ? 'pointer' : 'default',
                      transition: 'color 120ms ease, background 120ms ease, border-color 120ms ease, box-shadow 120ms ease',
                    },
                    title: setDraft && target ? '填入移动指令' : undefined,
                    onMouseEnter: setDraft && target ? (event: any) => {
                      event.currentTarget.style.color = '#f0cf82'
                      event.currentTarget.style.background = 'rgba(200,164,86,0.14)'
                      event.currentTarget.style.borderColor = '#b1873b'
                      event.currentTarget.style.boxShadow = '0 0 6px rgba(200,164,86,0.22)'
                    } : undefined,
                    onMouseLeave: setDraft && target ? (event: any) => {
                      event.currentTarget.style.color = '#e8dcc4'
                      event.currentTarget.style.background = 'rgba(200,164,86,0.05)'
                      event.currentTarget.style.borderColor = 'rgba(138,106,42,0.4)'
                      event.currentTarget.style.boxShadow = 'none'
                    } : undefined,
                    onClick: setDraft && target ? () => setDraft('前往' + target) : undefined,
                    children: jsxs('div', {
                      style: { display: 'flex', justifyContent: 'space-between', gap: 6 },
                      children: [
                        jsx('span', { style: { color: DIM_COLOR }, children: direction }),
                        jsx('span', { children: target || '—' }),
                      ],
                    }),
                  })
                }),
              }),
            ],
          }) : null,
        ],
      }) : null,
      interaction ? jsx(CardInteractionModal, {
        kind: interaction.kind,
        data: interaction.data,
        loading: interaction.loading,
        busy: interaction.busy,
        error: interaction.error,
        onClose: closeInteraction,
        onSubmit: (action: Record<string, unknown>) => { void submitInteraction(action) },
      }) : null,
    ],
  })
}
