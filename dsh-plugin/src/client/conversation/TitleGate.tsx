// 开始游戏入口：composer 工具行的常驻按钮（仅武侠GM 会话可见）。点击直调 engine
// 拉标题页数据，以模态直出 TitleCard（零 LLM）；建号/读档经隐藏命令转交 GM 回合
// 后自动收起；对话中已有游戏回合（正式开局）时按钮置灰禁用。

import { useCallback, useState } from 'react'
import { createPortal } from 'react-dom'
import { jsx, jsxs } from 'react/jsx-runtime'
import type { DeleteRequest } from './delete-api'
import { useGameActive, type GameActivity } from './game-active'
import { TitleCard } from './TitleCard'
import type { TitleRequest } from './title-api'

// dsh preset id = 安装目录名（~/.dsh/.agent-presets/wuxia，显示名"武侠GM"）
const WUXIA_PRESET_ID = 'wuxia'

interface TitleData {
  saves: any[]
  nextSlot?: number
  version?: string
}

export function TitleGate({ sessionId, useSessions, command, titleRequest, deleteRequest, gameActivity }: {
  sessionId?: string
  useSessions: (selector: (state: any) => any) => any
  command?: (line: string) => void
  titleRequest?: TitleRequest
  deleteRequest?: DeleteRequest
  gameActivity?: GameActivity
}) {
  const [open, setOpen] = useState(false)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')
  const [title, setTitle] = useState<TitleData | null>(null)

  // 仅武侠GM 会话显示入口；会话未记录 preset 时为 undefined
  const presetId = useSessions((state: any) => {
    const value = state?.byId?.[sessionId]?.projectionValues?.agentPreset
    return typeof value === 'string' ? value : undefined
  })
  const gameActive = useGameActive(gameActivity)

  const enter = useCallback(() => {
    if (!titleRequest || loading) return
    setLoading(true)
    setError('')
    void titleRequest().then(
      (res) => {
        setTitle({ saves: res.存档列表, nextSlot: res.next_slot, version: res.版本 })
        setLoading(false)
        setOpen(true)
      },
      (err) => {
        setError(err instanceof Error ? err.message : String(err))
        setLoading(false)
      },
    )
  }, [titleRequest, loading])

  // 建号/读档经隐藏命令开 GM 回合，标题模态随之让位给对话流
  const gateCommand = useCallback((line: string) => {
    if (/^\/wuxia-(?:create|load)(?:\s|$)/.test(line)) setOpen(false)
    command?.(line)
  }, [command])

  if (!titleRequest || presetId !== WUXIA_PRESET_ID) return null

  const disabled = loading || gameActive

  return jsxs('div', {
    style: { display: 'flex', alignItems: 'center', gap: 6 },
    children: [
      jsx('button', {
        type: 'button',
        disabled,
        title: gameActive ? '游戏已在对话中进行' : '直接进入武侠RPG标题页（不经 GM）',
        onClick: enter,
        style: {
          display: 'flex', alignItems: 'center', gap: 4,
          padding: '2px 10px', fontSize: 12, whiteSpace: 'nowrap',
          color: '#c8a456', background: 'transparent',
          border: '1px solid #8a6a2a', borderRadius: 6,
          cursor: disabled ? 'default' : 'pointer', opacity: disabled ? 0.45 : 1,
        },
        children: loading ? '进入中…' : '⚔ 开始游戏',
      }),
      error ? jsx('span', { style: { color: '#c45a4a', fontSize: 11 }, children: error }) : null,
      open && title ? createPortal(
        jsx('div', {
          style: {
            position: 'fixed', inset: 0, zIndex: 10000,
            background: 'rgba(8,6,4,0.72)',
            display: 'flex', alignItems: 'flex-start', justifyContent: 'center',
            overflowY: 'auto', padding: '48px 16px',
          },
          onClick: () => setOpen(false),
          children: jsxs('div', {
            style: { width: 'min(760px, 100%)' },
            onClick: event => event.stopPropagation(),
            children: [
              jsx('div', {
                style: { display: 'flex', justifyContent: 'flex-end', marginBottom: 6 },
                children: jsx('button', {
                  type: 'button',
                  onClick: () => setOpen(false),
                  style: {
                    padding: '2px 12px', fontSize: 12,
                    color: '#9a8c6e', background: 'transparent',
                    border: '1px solid #3a2f22', borderRadius: 6, cursor: 'pointer',
                  },
                  children: '✕ 关闭',
                }),
              }),
              jsx(TitleCard, {
                saves: title.saves,
                nextSlot: title.nextSlot,
                version: title.version,
                command: gateCommand,
                deleteRequest,
              }),
            ],
          }),
        }),
        document.body,
      ) : null,
    ],
  })
}
