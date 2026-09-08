import { useCallback, useEffect, useLayoutEffect, useRef, useState } from 'react'
import { createPortal } from 'react-dom'
import type { PanelRequest } from './panel-api'
import { applyPartyState, useParty } from './party-store'
import { useBattleMode } from './battle-mode'
import { PANEL_BUTTONS, PanelContent, panelLabel, type PanelKind } from './panels/PanelContent'

const LEFT_WIDTH = 230
const PANEL_WIDTH = 560
const EXPANDED_WIDTH = LEFT_WIDTH + PANEL_WIDTH
const EXPANDED_HEIGHT = 480
const VIEWPORT_GAP = 8

function fmtMoney(value: number | null): string {
  if (value == null) return '—'
  return value >= 10000 ? (value / 10000).toFixed(1).replace(/\.0$/, '') + '万' : String(value)
}

function clampPosition(
  value: { x: number; y: number },
  width: number,
  height: number,
  viewport: { width: number; height: number },
): { x: number; y: number } {
  const maxX = Math.max(0, viewport.width - width)
  const maxY = Math.max(0, viewport.height - height)
  return {
    x: Math.max(0, Math.min(maxX, value.x)),
    y: Math.max(0, Math.min(maxY, value.y)),
  }
}

// 浮窗位置：模块级持久化（会话切换/重挂载不丢坐标）
let partyPosition = { x: 0, y: 0 }
let partyPositionInitialized = false

export function PartyFloat(props: {
  sessionId?: string
  panelRequest?: PanelRequest
  command?: (line: string) => void
}) {
  const party = useParty()
  const battleActive = useBattleMode(state => state.active)
  const [open, setOpen] = useState(true)
  const [activePanel, setActivePanel] = useState<PanelKind | null>(null)
  const [viewport, setViewport] = useState(() => ({
    width: typeof window === 'undefined' ? 1280 : window.innerWidth,
    height: typeof window === 'undefined' ? 800 : window.innerHeight,
  }))
  const [pos, setPos] = useState(() => {
    if (!partyPositionInitialized) {
      partyPosition.x = 16
      partyPosition.y = 80
      partyPositionInitialized = true
    }
    return { x: partyPosition.x, y: partyPosition.y }
  })
  const floatRef = useRef<HTMLDivElement>(null)
  const [dragging, setDragging] = useState(false)

  // composer dock 会按会话重挂载；若复用同一实例，sessionId 变化也会主动清空。
  useEffect(() => {
    useParty.getState().clear()
    useBattleMode.getState().clear()
    setActivePanel(null)
  }, [props.sessionId])

  useEffect(() => {
    const onResize = () => setViewport({ width: window.innerWidth, height: window.innerHeight })
    window.addEventListener('resize', onResize)
    return () => window.removeEventListener('resize', onResize)
  }, [])

  const visible = party.成员.length > 0 || party.体力 != null || party.金钱 != null
  const expanded = open && activePanel !== null
  const floatWidth = expanded
    ? Math.min(EXPANDED_WIDTH, Math.max(LEFT_WIDTH, viewport.width - VIEWPORT_GAP))
    : LEFT_WIDTH
  const maxFloatHeight = Math.max(40, viewport.height - VIEWPORT_GAP * 2)
  const expandedHeight = Math.min(EXPANDED_HEIGHT, maxFloatHeight)

  useLayoutEffect(() => {
    if (!visible) return
    const element = floatRef.current
    if (!element) return

    const constrain = () => {
      const bounds = element.getBoundingClientRect()
      setPos(previous => {
        const next = clampPosition(previous, bounds.width, bounds.height, viewport)
        partyPosition = next
        return next.x === previous.x && next.y === previous.y ? previous : next
      })
    }

    constrain()
    if (typeof ResizeObserver === 'undefined') return
    const observer = new ResizeObserver(constrain)
    observer.observe(element)
    return () => observer.disconnect()
  }, [expanded, expandedHeight, floatWidth, open, viewport, visible])

  const request = useCallback<PanelRequest>(async (slot, actions) => {
    if (!props.panelRequest) throw new Error('当前会话暂不可调用功能面板')
    const response = await props.panelRequest(slot, actions)
    applyPartyState(response.state)
    return response
  }, [props.panelRequest])

  const onDragStart = (event: any) => {
    if (event.target.closest('[data-no-drag]')) return
    event.preventDefault()
    const startX = event.clientX
    const startY = event.clientY
    const originX = pos.x
    const originY = pos.y
    setDragging(true)
    const onMove = (moveEvent: MouseEvent) => {
      const bounds = floatRef.current?.getBoundingClientRect()
      const next = clampPosition({
        x: originX + moveEvent.clientX - startX,
        y: originY + moveEvent.clientY - startY,
      }, bounds?.width ?? floatWidth, bounds?.height ?? 40, {
        width: window.innerWidth,
        height: window.innerHeight,
      })
      partyPosition = next
      setPos(next)
    }
    const onUp = () => {
      setDragging(false)
      window.removeEventListener('mousemove', onMove)
      window.removeEventListener('mouseup', onUp)
    }
    window.addEventListener('mousemove', onMove)
    window.addEventListener('mouseup', onUp)
  }

  // 无队伍数据时不显示浮窗（门厅/未开档）
  if (!visible) return null
  // 战斗进行中或终局待结算时隐藏浮窗，避免遮挡战场
  if (battleActive) return null
  const members = party.成员
  const memberSlots = Array.from({ length: 4 }, (_, index) => members[index] ?? null)
  const memberNames = members.map(member => member.名称).filter(Boolean)
  const saveEnabled = party.slot != null && Boolean(props.panelRequest)
  const loadEnabled = saveEnabled && Boolean(props.command)

  const featureButton = (item: { kind: PanelKind; label: string }) => {
    const active = activePanel === item.kind
    const enabled = party.slot != null && Boolean(props.panelRequest)
    return (
      <button
        key={item.kind}
        type="button"
        disabled={!enabled}
        onClick={() => setActivePanel(value => value === item.kind ? null : item.kind)}
        style={{
          padding: '6px 0', fontSize: 12,
          color: active ? '#f0cf82' : '#c8a456',
          background: active ? '#352815' : 'transparent',
          border: `1px solid ${active ? '#b1873b' : '#8a6a2a'}`,
          borderRadius: 5, cursor: enabled ? 'pointer' : 'default',
          opacity: enabled ? 1 : 0.42,
        }}
      >
        {item.label}
      </button>
    )
  }

  return createPortal(
    <div ref={floatRef} style={{
      position: 'fixed', left: pos.x, top: pos.y, zIndex: 9999,
      display: 'flex', alignItems: 'stretch', width: floatWidth, maxWidth: '100vw',
      height: expanded ? expandedHeight : 'auto', maxHeight: maxFloatHeight,
      borderRadius: 10, border: '2px solid #8a6a2a', background: '#1a1612',
      boxShadow: '0 0 0 1px rgba(200,164,86,0.18), 0 6px 24px rgba(0,0,0,0.62)', color: '#e8dcc4',
      fontSize: 13, overflow: 'hidden', userSelect: 'none',
      fontFamily: 'system-ui, -apple-system, "PingFang SC", "Microsoft YaHei", sans-serif',
    }}>
      <div style={{ flex: `0 0 ${LEFT_WIDTH}px`, minWidth: 0, display: 'flex', flexDirection: 'column', maxHeight: maxFloatHeight }}>
        <div
          style={{
            display: 'flex', alignItems: 'center', justifyContent: 'space-between',
            padding: '8px 12px', cursor: dragging ? 'grabbing' : 'grab',
            borderBottom: open ? '1px solid #3a2f22' : 'none', background: '#221c16',
          }}
          onMouseDown={onDragStart}
        >
          <span style={{ color: '#c8a456', fontWeight: 600, letterSpacing: 2 }}>
            当 前 队 伍
            {party.slot != null ? <span style={{ marginLeft: 8, fontSize: 11, color: '#9a8c6e' }}>slot {party.slot}</span> : null}
          </span>
          <button
            type="button"
            data-no-drag="1"
            aria-label={open ? '收起队伍浮窗' : '展开队伍浮窗'}
            style={{ color: '#9a8c6e', fontSize: 11, cursor: 'pointer', padding: '0 4px', border: 0, background: 'transparent' }}
            onClick={() => setOpen(value => !value)}
          >
            {open ? '▾' : '▸'}
          </button>
        </div>
        {open ? (
          <div style={{ flex: '1 1 auto', minHeight: 0, padding: '10px 12px', overflowY: 'auto' }}>
            <div style={{ display: 'flex', gap: 6, marginBottom: 10 }}>
              <button
                type="button"
                style={{
                  flex: 1, padding: '5px 0', fontSize: 12.5,
                  color: activePanel === 'save' ? '#b8d89b' : '#7a9a5a',
                  background: activePanel === 'save' ? '#24321f' : 'transparent',
                  border: `1px solid ${activePanel === 'save' ? '#6f8a55' : '#4a5a3a'}`,
                  borderRadius: 5, cursor: saveEnabled ? 'pointer' : 'default',
                  opacity: saveEnabled ? 1 : 0.42,
                }}
                disabled={!saveEnabled}
                onClick={() => setActivePanel(value => value === 'save' ? null : 'save')}
              >存档</button>
              <button
                type="button"
                style={{
                  flex: 1, padding: '5px 0', fontSize: 12.5,
                  color: activePanel === 'load' ? '#f0cf82' : '#c8a456',
                  background: activePanel === 'load' ? '#352815' : 'transparent',
                  border: `1px solid ${activePanel === 'load' ? '#b1873b' : '#8a6a2a'}`,
                  borderRadius: 5, cursor: loadEnabled ? 'pointer' : 'default',
                  opacity: loadEnabled ? 1 : 0.42,
                }}
                disabled={!loadEnabled}
                onClick={() => setActivePanel(value => value === 'load' ? null : 'load')}
              >读档</button>
            </div>
            <div style={{ display: 'flex', gap: 16, marginBottom: 10, fontSize: 12, color: '#9a8c6e' }}>
              <div>体力 <b style={{ color: '#e8dcc4', fontSize: 13 }}>{party.体力 == null ? '—' : party.体力}</b></div>
              <div>金钱 <b style={{ color: '#e8dcc4', fontSize: 13 }}>{fmtMoney(party.金钱)}</b></div>
            </div>
            {memberSlots.map((member, index) => {
              if (!member) {
                return (
                  <div key={`empty:${index}`} style={{ padding: '6px 0', borderTop: index > 0 ? '1px solid #6f5527' : 'none' }}>
                    <div style={{ marginBottom: 5, fontSize: 13, color: '#9a8c6e' }}>（空位）</div>
                    <div style={{ height: 14, borderRadius: 3, background: '#0f0d0a', marginBottom: 4, border: '1px solid #3a2f22' }} />
                    <div style={{ height: 14, borderRadius: 3, background: '#0f0d0a', border: '1px solid #3a2f22' }} />
                  </div>
                )
              }
              const hp = Math.max(0, Math.min(100, ((member.气血 || 0) / (member.气血上限 || 1)) * 100))
              const mp = Math.max(0, Math.min(100, ((member.内力 || 0) / (member.内力上限 || 1)) * 100))
              return (
                <div key={`${member.名称}:${index}`} style={{ padding: '6px 0', borderTop: index > 0 ? '1px solid #6f5527' : 'none' }}>
                  <div style={{ marginBottom: 5, fontSize: 13, color: '#e8dcc4' }}>{member.名称}</div>
                  <div style={{ position: 'relative', height: 14, borderRadius: 3, background: '#0f0d0a', marginBottom: 4, overflow: 'hidden', border: '1px solid #3a2f22' }}>
                    <div style={{ position: 'absolute', inset: 0, width: hp + '%', background: hp < 35 ? '#a83232' : '#8a4a3a' }} />
                    <span style={{ position: 'absolute', inset: 0, display: 'flex', alignItems: 'center', justifyContent: 'center', fontSize: 10, color: '#fff', textShadow: '0 1px 2px rgba(0,0,0,0.8)' }}>
                      气血 {member.气血}/{member.气血上限}
                    </span>
                  </div>
                  <div style={{ position: 'relative', height: 14, borderRadius: 3, background: '#0f0d0a', overflow: 'hidden', border: '1px solid #3a2f22' }}>
                    <div style={{ position: 'absolute', inset: 0, width: mp + '%', background: '#3a5a8a' }} />
                    <span style={{ position: 'absolute', inset: 0, display: 'flex', alignItems: 'center', justifyContent: 'center', fontSize: 10, color: '#fff', textShadow: '0 1px 2px rgba(0,0,0,0.8)' }}>
                      内力 {member.内力}/{member.内力上限}
                    </span>
                  </div>
                </div>
              )
            })}
            <div style={{ display: 'grid', gridTemplateColumns: 'repeat(3, 1fr)', gap: 4, marginTop: 10 }}>
              {PANEL_BUTTONS.map(featureButton)}
            </div>
          </div>
        ) : null}
      </div>

      {expanded && activePanel && party.slot != null ? (
        <div style={{
          flex: '1 1 auto', minWidth: 0, display: 'flex', flexDirection: 'column', maxHeight: maxFloatHeight,
          borderLeft: '1px solid #8a6a2a', background: '#1d1813', userSelect: 'text',
        }}>
          <div
            style={{
              flex: '0 0 auto', display: 'flex', alignItems: 'center', justifyContent: 'space-between',
              padding: '8px 12px', background: '#221c16', borderBottom: '1px solid #3a2f22',
              cursor: dragging ? 'grabbing' : 'grab',
            }}
            onMouseDown={onDragStart}
          >
            <span style={{ color: '#c8a456', fontWeight: 600, letterSpacing: 2 }}>{panelLabel(activePanel)}</span>
            <button
              type="button"
              data-no-drag="1"
              aria-label="关闭功能面板"
              onClick={() => setActivePanel(null)}
              style={{ padding: '1px 6px', color: '#9a8c6e', background: 'transparent', border: '1px solid #4a3a27', borderRadius: 5, cursor: 'pointer', fontSize: 13 }}
            >×</button>
          </div>
          <div style={{ flex: '1 1 auto', minHeight: 0, padding: '10px 12px 14px', overflow: 'auto' }}>
            <PanelContent
              key={`${party.slot}:${activePanel}`}
              kind={activePanel}
              slot={party.slot}
              members={memberNames}
              request={request}
              command={props.command}
              onLoadRequested={() => setActivePanel(null)}
            />
          </div>
        </div>
      ) : null}
    </div>,
    document.body,
  )
}
