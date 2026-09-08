import { useCallback, useEffect, useState } from 'react'
import {
  displayValue, EmptyState, engineError, LoadingState, PanelButton,
  PanelNotice, PanelTable, resultNotice, SectionTitle, type PanelProps,
} from './PanelPrimitives'

const EQUIP_SLOTS = ['武器1', '武器2', '护甲', '饰品', '冠巾']
const WEAPON_SUBS = new Set(['刀', '剑', '奇门', '搏击', '暗器', '长兵'])
const SLOT_BY_SUB: Record<string, string> = { 护甲: '护甲', 饰品: '饰品', 冠巾: '冠巾' }

export function EquipPanel({ slot, request }: PanelProps) {
  const [data, setData] = useState<any>(null)
  const [loading, setLoading] = useState(true)
  const [busy, setBusy] = useState<string | null>(null)
  const [error, setError] = useState('')
  const [notice, setNotice] = useState('')

  const refresh = useCallback(async (showLoading = true) => {
    if (showLoading) setLoading(true)
    setError('')
    try {
      const response = await request(slot, [{ 类型: '配置装备' }])
      const next = response.results[0]
      const err = engineError(next)
      if (err) throw new Error(err)
      setData(next)
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : String(caught))
    } finally {
      setLoading(false)
    }
  }, [request, slot])

  useEffect(() => { void refresh() }, [refresh])

  const act = async (key: string, action: Record<string, unknown>) => {
    if (busy) return
    setBusy(key)
    setError('')
    setNotice('')
    try {
      const response = await request(slot, [action])
      const result = response.results[0]
      const err = engineError(result)
      if (err) throw new Error(err)
      setNotice(resultNotice(result) || '装备已更新')
      await refresh(false)
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : String(caught))
    } finally {
      setBusy(null)
    }
  }

  const current = (data?.当前装备 || {}) as Record<string, string | null>
  const available = Array.isArray(data?.可换装备) ? data.可换装备 : []

  return (
    <div>

      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', gap: 8 }}>
        <span style={{ color: '#9a8c6e', fontSize: 12 }}>角色：{data?.角色 || '主控'}</span>
        <PanelButton disabled={loading || Boolean(busy)} onClick={() => void refresh()}>刷新</PanelButton>
      </div>
      <PanelNotice kind="error">{error}</PanelNotice>
      <PanelNotice kind="notice">{notice}</PanelNotice>
      {loading && !data ? <LoadingState /> : (
        <>
          <SectionTitle>当前装备</SectionTitle>
          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(145px, 1fr))', gap: 6 }}>
            {EQUIP_SLOTS.map(equipSlot => {
              const item = current[equipSlot]
              return (
                <div key={equipSlot} style={{ padding: '8px 9px', background: '#17130f', border: '1px solid #3a2f22', borderRadius: 6 }}>
                  <div style={{ color: '#9a8c6e', fontSize: 11, marginBottom: 4 }}>{equipSlot}</div>
                  <div style={{ color: '#e8dcc4', minHeight: 20, marginBottom: 5, overflowWrap: 'anywhere' }}>{item || '（空）'}</div>
                  {item ? (
                    <PanelButton danger disabled={Boolean(busy)} onClick={() => void act(`remove:${equipSlot}`, { 类型: '配置装备', 操作: '脱', 槽位: equipSlot })}>
                      {busy === `remove:${equipSlot}` ? '卸下中…' : '卸下'}
                    </PanelButton>
                  ) : null}
                </div>
              )
            })}
          </div>

          <SectionTitle>物品栏可换装备</SectionTitle>
          {available.length ? (
            <PanelTable
              headers={['名称', '类型', '品级', '操作']}
              rows={available.map((item: any) => {
                const isWeapon = item.类型 === '武器' || WEAPON_SUBS.has(item.子类型)
                const target = EQUIP_SLOTS.includes(item.类型) ? item.类型 : SLOT_BY_SUB[item.子类型]
                return [
                  <b>{displayValue(item.名称)}</b>,
                  [item.类型, item.子类型].filter(Boolean).join(' · ') || '—',
                  item.品名 || displayValue(item.品级),
                  isWeapon ? (
                    <span style={{ whiteSpace: 'nowrap' }}>
                      <PanelButton disabled={Boolean(busy)} onClick={() => void act(`wear:${item.名称}:1`, { 类型: '配置装备', 操作: '穿', 槽位: '武器1', 物品: item.名称 })}>武器1</PanelButton>
                      <PanelButton disabled={Boolean(busy)} onClick={() => void act(`wear:${item.名称}:2`, { 类型: '配置装备', 操作: '穿', 槽位: '武器2', 物品: item.名称 })}>武器2</PanelButton>
                    </span>
                  ) : target ? (
                    <PanelButton disabled={Boolean(busy)} onClick={() => void act(`wear:${item.名称}`, { 类型: '配置装备', 操作: '穿', 槽位: target, 物品: item.名称 })}>
                      {busy === `wear:${item.名称}` ? '穿戴中…' : '穿上'}
                    </PanelButton>
                  ) : '不适用',
                ]
              })}
            />
          ) : <EmptyState>（无可换装备）</EmptyState>}
        </>
      )}
    </div>
  )
}
