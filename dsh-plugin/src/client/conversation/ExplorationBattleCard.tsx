import { useRef, useState } from 'react'
import type { BattleRequest } from './battle-api'
import { useBattleMode } from './battle-mode'
import { CARD_STYLE, BORDER_COLOR, DIM_COLOR, ExplorationSummary, TITLE_COLOR } from './ExplorationSummary'
import { useParty } from './party-store'
import { engineError, PanelNotice } from './panels/PanelPrimitives'

const CONTROL_DESCRIPTION: Record<string, string> = {
  玩家角色: '仅操控主控角色，其余角色由 AI 行动',
  我方全员: '操控我方所有参战角色',
  AI自动: '我方全由 AI 操控，直接观战至战斗结束',
}

export function ExplorationBattleCard({
  data, battleRequest, onStarted, locked,
}: {
  data: any
  battleRequest?: BattleRequest
  onStarted: (data: Record<string, any>) => void
  /** 所属回合已被新回合取代：过时快照，控件永久禁用、仅供回顾 */
  locked?: boolean
}) {
  const [selected, setSelected] = useState<string | null>(null)
  const [phase, setPhase] = useState<'idle' | 'starting' | 'failed' | 'started'>('idle')
  const [error, setError] = useState('')
  const requestId = useRef(0)

  const allies = Array.isArray(data?.我方) ? data.我方.map(String).filter(Boolean) : []
  const enemies = Array.isArray(data?.敌方) ? data.敌方.map(String).filter(Boolean) : []
  const options = Array.isArray(data?.操控选项) && data.操控选项.length
    ? data.操控选项.map(String).filter(Boolean)
    : ['玩家角色']

  const resolveSlot = (): number | null => {
    const fromCard = Number(data?.槽位)
    if (Number.isInteger(fromCard) && fromCard > 0) return fromCard
    return useParty.getState().slot
  }

  const start = async (control: string) => {
    if (locked || phase === 'starting' || phase === 'started') return
    if (!battleRequest) {
      setError('当前会话暂不可调用战斗功能')
      return
    }
    const slot = resolveSlot()
    if (slot == null) {
      setError('当前战前 Card 缺少有效存档槽位')
      return
    }
    const currentRequest = ++requestId.current
    setSelected(control)
    setPhase('starting')
    setError('')
    try {
      const response = await battleRequest({
        operation: 'start',
        slot,
        allies,
        enemies,
        allowEscape: Boolean(data?.允许逃跑),
        control,
      })
      if (currentRequest !== requestId.current) return
      const result = response.result
      const failed = engineError(result)
      if (failed) throw new Error(failed)
      if (result?.界面 !== 'battle-ui' && result?.界面 !== 'battle-end-ui') {
        throw new Error(`engine 未返回战斗界面（实际：${String(result?.界面 || '无界面')}）`)
      }
      setPhase('started')
      // 开战成功：进入战斗模式，隐藏队伍状态浮窗（战斗中队伍状态不落盘，浮窗留战前快照易误导且遮挡战场）
      useBattleMode.getState().setActive(true)
      onStarted(result)
    } catch (caught) {
      if (currentRequest !== requestId.current) return
      setPhase('failed')
      setError(caught instanceof Error ? caught.message : String(caught))
    }
  }

  const busy = phase === 'starting'
  const committed = selected !== null

  return (
    <div style={{ ...CARD_STYLE, position: 'relative' }}>
      <ExplorationSummary data={data} />
      {/* 与游历卡同观感：概要区保持亮色，只置灰下方控件区（内容层置灰，根节点保持不透明） */}
      <div
        title={locked ? '回合已推进，此卡仅供回顾' : undefined}
        style={{
          opacity: locked ? 0.55 : 1,
          pointerEvents: locked ? 'none' : 'auto',
          transition: 'opacity 150ms ease',
        }}
      >
      <div style={{ borderTop: `1px dashed ${BORDER_COLOR}`, paddingTop: 12, marginTop: 5 }}>
        <div style={{ textAlign: 'center', color: TITLE_COLOR, fontSize: 18, letterSpacing: 5, marginBottom: 9 }}>
          短 兵 相 接
        </div>
        <div style={{ display: 'grid', gap: 6, maxWidth: 620, margin: '0 auto 12px' }}>
          <div style={{ display: 'flex', justifyContent: 'center', gap: 9, flexWrap: 'wrap' }}>
            <b style={{ color: TITLE_COLOR }}>我方</b>
            <span>{allies.join('、') || '—'}</span>
          </div>
          <div style={{ display: 'flex', justifyContent: 'center', gap: 9, flexWrap: 'wrap' }}>
            <b style={{ color: '#d99a7a' }}>敌方</b>
            <span>{enemies.join('、') || '—'}</span>
          </div>
        </div>
        <div style={{ color: DIM_COLOR, textAlign: 'center', fontSize: 12, marginBottom: 9 }}>
          {phase === 'started' ? '战斗已经开始' : busy ? '正在铺开战局…' : '选择操控方式后开战'}
        </div>
        <PanelNotice kind="error">{error}</PanelNotice>
        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(150px, 1fr))', gap: 8, maxWidth: 680, margin: '0 auto' }}>
          {options.map((option: string) => {
            const chosen = selected === option
            return (
              <button
                key={option}
                type="button"
                disabled={!battleRequest || committed}
                onClick={() => { void start(option) }}
                style={{
                  padding: '9px 10px', minWidth: 0, textAlign: 'left',
                  border: `1px solid ${chosen ? '#b1873b' : '#6f5527'}`,
                  borderRadius: 7, background: chosen ? '#352815' : '#1a1612',
                  color: chosen ? '#f0cf82' : TITLE_COLOR,
                  cursor: !battleRequest || committed ? 'default' : 'pointer',
                  opacity: committed && !chosen ? 0.4 : 1,
                  fontFamily: 'inherit',
                }}
              >
                <div style={{ fontSize: 13, letterSpacing: 1, marginBottom: 2 }}>
                  {chosen && phase === 'started' ? '✓ ' : ''}{option}
                </div>
                <div style={{ color: DIM_COLOR, fontSize: 10.5, lineHeight: 1.45 }}>
                  {CONTROL_DESCRIPTION[option] || '按此方式进入战斗'}
                </div>
              </button>
            )
          })}
        </div>
        {phase === 'failed' && selected ? (
          <div style={{ textAlign: 'center', marginTop: 10 }}>
            <button
              type="button"
              onClick={() => { void start(selected) }}
              style={{
                padding: '6px 16px', border: '1px solid #8a6a2a', borderRadius: 6,
                background: '#2a2318', color: TITLE_COLOR, cursor: 'pointer', fontFamily: 'inherit',
              }}
            >重新开战</button>
          </div>
        ) : null}
      </div>
      </div>
    </div>
  )
}
