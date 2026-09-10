import { useCallback, useEffect, useRef, useState } from 'react'
import { jsx, jsxs } from 'react/jsx-runtime'
import { CreateWizardPanel, type CharacterDraft } from './CreateWizardPanel'
import type { DeleteRequest } from './delete-api'

function loadCommand(slot: number, target: string, label: string): string {
  return `/wuxia-load ${JSON.stringify({ slot, target, label })}`
}

function createCommand(slot: number, character: CharacterDraft): string {
  return `/wuxia-create ${JSON.stringify({ slot, character })}`
}

function SaveSlotCard({ save, command, onDelete }: {
  save: any
  command?: (line: string) => void
  onDelete?: () => void
}) {
  const [open, setOpen] = useState(false)
  const points = save.saves || []
  const count = points.length

  const onLoadLatest = () => {
    if (!command) return
    if (!confirm(`读取 slot ${save.slot}（${save.角色名 || ''}）的最新存档？`)) return
    command(loadCommand(save.slot, save.最近存档 || '', save.角色名 || save.最近存档 || ''))
  }
  const onLoadPoint = (point: any) => {
    if (!command) return
    if (!confirm(`读取存档「${point.label || point.时间戳}」？`)) return
    command(loadCommand(save.slot, point.时间戳 || '', point.label || point.时间戳 || ''))
  }

  return jsxs('div', {
    style: { margin: '6px 0' },
    children: [
      jsxs('div', {
        style: {
          display: 'flex', alignItems: 'center', gap: 8,
          padding: '8px 12px', background: '#1a1612', borderRadius: 8,
          border: '1px solid #3a2f22',
        },
        children: [
          jsx('button', {
            style: {
              background: 'transparent', color: '#9a8c6e',
              border: '1px solid #3a2f22', borderRadius: 6,
              padding: '2px 8px', cursor: count > 0 ? 'pointer' : 'default',
              fontSize: 12, opacity: count > 0 ? 1 : 0.4,
            },
            disabled: count === 0,
            onClick: () => setOpen(value => !value),
            children: count > 0 ? `${open ? '▾' : '▸'} ${count}点` : '—',
          }),
          jsx('div', {
            style: { flex: 1, fontSize: 13, color: '#e8dcc4' },
            children: `slot ${save.slot} · ${save.角色名 || '（无名）'}`,
          }),
          jsx('div', {
            style: { fontSize: 12, color: '#9a8c6e' },
            children: `最近 ${save.最近存档 || '—'}`,
          }),
          jsx('button', {
            style: { background: 'transparent', color: '#c8a456', border: '1px solid #8a6a2a', borderRadius: 6, padding: '4px 12px', cursor: command ? 'pointer' : 'default', fontSize: 13, opacity: command ? 1 : 0.4 },
            disabled: !command,
            onClick: onLoadLatest,
            children: '读取最新',
          }),
          jsx('button', {
            style: { background: 'transparent', color: '#c45a4a', border: '1px solid #3a2f22', borderRadius: 6, padding: '4px 12px', cursor: onDelete ? 'pointer' : 'default', fontSize: 13, opacity: onDelete ? 1 : 0.4 },
            disabled: !onDelete,
            onClick: onDelete,
            children: '删档',
          }),
        ],
      }),
      open && count > 0 ? jsx('div', {
        style: { borderLeft: '2px solid #8a6a2a', margin: '4px 0 8px 24px', paddingLeft: 10 },
        children: points.map((point: any, index: number) =>
          jsxs('div', {
            style: {
              display: 'flex', alignItems: 'center', gap: 8,
              padding: '4px 4px', borderBottom: '1px dashed #3a2f22', fontSize: 12,
            },
            children: [
              jsx('span', { style: { flex: 1, color: '#e8dcc4' }, children: point.label || '（未命名）' }),
              jsx('span', {
                style: { color: '#9a8c6e', fontFamily: 'Consolas, monospace', fontSize: 11 },
                children: `#${point.序号 ?? ''} ${point.时间戳 || ''}`,
              }),
              jsx('button', {
                style: { background: 'transparent', color: '#c8a456', border: '1px solid #8a6a2a', borderRadius: 6, padding: '2px 10px', cursor: command ? 'pointer' : 'default', fontSize: 12, opacity: command ? 1 : 0.4 },
                disabled: !command,
                onClick: () => onLoadPoint(point),
                children: '读取',
              }),
            ],
          }, index),
        ),
      }) : null,
    ],
  })
}

const LOGO = `██╗    ██╗██╗   ██╗██╗  ██╗
██║    ██║██║   ██║╚██╗██╔╝
██║ █╗ ██║██║   ██║ ╚███╔╝
██║███╗██║██║   ██║ ██╔██╗
╚███╔███╔╝╚██████╔╝██╔╝ ██╗
 ╚══╝╚══╝  ╚═════╝ ╚═╝  ╚═╝

        ── 武 侠 R P G ──`

export function TitleCard({ saves, nextSlot, version, command, deleteRequest, locked }: {
  saves?: any[]
  nextSlot?: number
  version?: string
  command?: (line: string) => void
  deleteRequest?: DeleteRequest
  /** 所属回合已被新回合取代：过时快照，控件永久禁用、仅供回顾 */
  locked?: boolean
}) {
  const [wizardOpen, setWizardOpen] = useState(false)
  const [gameStarting, setGameStarting] = useState(false)
  const [deleting, setDeleting] = useState(false)
  const [deleteError, setDeleteError] = useState('')
  // 删除后用 engine 返回的最新标题数据覆盖显示（props 不会自动刷新）
  const [overrideSaves, setOverrideSaves] = useState<any[] | null>(null)
  const [overrideNextSlot, setOverrideNextSlot] = useState<number | null>(null)
  const cardRef = useRef<HTMLDivElement | null>(null)
  const slots = overrideSaves ?? saves ?? []
  const availableSlot = overrideNextSlot ?? nextSlot
  const canCreate = Boolean(command) && Number.isInteger(availableSlot) && Number(availableSlot) > 0
  const existingNames = slots.map((save: any) => String(save?.角色名 || '')).filter(Boolean)
  const closeWizard = useCallback(() => setWizardOpen(false), [])
  const titleCommand = useCallback((line: string) => {
    if (!command) return
    if (/^\/wuxia-(?:create|load)(?:\s|$)/.test(line)) setGameStarting(true)
    command(line)
  }, [command])
  const submit = useCallback((character: CharacterDraft) => {
    if (!Number.isInteger(availableSlot) || Number(availableSlot) <= 0) return
    titleCommand(createCommand(Number(availableSlot), character))
    setWizardOpen(false)
  }, [availableSlot, titleCommand])
  const handleDelete = useCallback((slot: number) => {
    if (!deleteRequest || deleting) return
    if (!confirm(`删除 slot ${slot} 整个角色档？不可恢复！`)) return
    setDeleting(true)
    setDeleteError('')
    void deleteRequest(slot).then(
      (res) => {
        setOverrideSaves(res.存档列表)
        setOverrideNextSlot(res.next_slot)
        setDeleting(false)
      },
      (err) => { setDeleteError(err instanceof Error ? err.message : String(err)); setDeleting(false) },
    )
  }, [deleteRequest, deleting])

  // 回合已被新回合取代时关掉创建向导：卡片状态已过时
  useEffect(() => {
    if (locked) setWizardOpen(false)
  }, [locked])

  useEffect(() => {
    const card = cardRef.current
    if (!card) return
    card.inert = Boolean(locked) || gameStarting
    return () => { card.inert = false }
  }, [locked, gameStarting])

  if (wizardOpen) {
    return jsx('div', {
      style: {
        padding: '14px', margin: '8px 0', borderRadius: 10,
        border: '2px solid #8a6a2a',
        boxShadow: '0 0 0 1px rgba(200,164,86,0.14), 0 4px 16px rgba(0,0,0,0.38)',
        background: 'var(--dsw-alias-bg-elevated, #0f0d0a)',
      },
      children: jsx(CreateWizardPanel, {
        existingNames,
        onClose: closeWizard,
        onSubmit: submit,
      }),
    })
  }

  return jsxs('div', {
    ref: cardRef,
    'aria-disabled': gameStarting || locked || undefined,
    title: locked ? '回合已推进，此卡仅供回顾' : undefined,
    style: {
      padding: '30px 20px', margin: '8px 0', borderRadius: 10,
      border: '2px solid #8a6a2a',
      boxShadow: '0 0 0 1px rgba(200,164,86,0.14), 0 4px 16px rgba(0,0,0,0.38)',
      background: 'var(--dsw-alias-bg-elevated, #0f0d0a)', textAlign: 'center',
    },
    // 与游历卡同观感：只置灰控件区（创建/存档列表），标题与说明文字保持亮色
    children: [
      jsx('pre', {
        style: { display: 'inline-block', textAlign: 'left', margin: 0, color: '#c8a456', fontSize: '11px', lineHeight: 1.18, fontFamily: 'Consolas, "SFMono-Regular", monospace' },
        children: LOGO,
      }),
      jsx('div', {
        style: { color: '#9a8c6e', letterSpacing: 2, marginTop: 12, fontSize: 14 },
        children: '江湖路远，剑未出鞘。少侠，从何而起？',
      }),
      jsxs('div', {
        style: { color: '#9a8c6e', fontSize: 12, marginTop: 6 },
        children: [`作者：可乐酸橙　版本：v${version || '0.0.0'}　`, `存档：${slots.length} 个`],
      }),
      jsx('div', {
        style: { color: '#7a9a5a', fontSize: 12.5, marginTop: 12, letterSpacing: 1 },
        children: '点上方按钮开新档，或读取存档续旧缘。',
      }),
      jsxs('div', {
        style: {
          opacity: locked ? 0.55 : 1,
          pointerEvents: locked ? 'none' : 'auto',
          transition: 'opacity 150ms ease',
        },
        children: [
          jsx('div', {
            style: { textAlign: 'center', margin: '14px 0 6px' },
            children: jsx('button', {
              style: { fontSize: 14, padding: '8px 26px', letterSpacing: 4, background: 'transparent', color: '#c8a456', border: '1px solid #8a6a2a', borderRadius: 6, cursor: canCreate ? 'pointer' : 'default', opacity: canCreate ? 1 : 0.45 },
              disabled: !canCreate,
              title: canCreate ? `使用 slot ${availableSlot} 创建角色` : '未取得可用存档槽位',
              onClick: canCreate ? () => setWizardOpen(true) : undefined,
              children: '＋ 创建角色',
            }),
          }),
          slots.length > 0 ? jsxs('div', {
            style: { maxWidth: 660, margin: '0 auto', textAlign: 'left' },
            children: [
              deleteError ? jsx('div', {
                style: { color: '#c45a4a', fontSize: 12, margin: '4px 0 8px' },
                children: deleteError,
              }) : null,
              deleting ? jsx('div', {
                style: { color: '#9a8c6e', fontSize: 12, margin: '4px 0 8px' },
                children: '正在删除…',
              }) : null,
              ...slots.slice(0, 15).map((save: any, index: number) =>
                jsx(SaveSlotCard, {
                  save,
                  command: titleCommand,
                  onDelete: deleteRequest ? () => handleDelete(save.slot) : undefined,
                }, index),
              ),
            ],
          }) : jsx('div', {
            style: { color: '#9a8c6e', fontSize: 13, textAlign: 'center', margin: '12px 0' },
            children: '尚无存档可续，可由创建向导开创新篇。',
          }),
        ],
      }),
    ],
  })
}
