import { useCallback, useEffect, useRef, useState } from 'react'
import {
  displayValue, EmptyState, engineError, LoadingState, PanelButton,
  PanelNotice, PanelTable, resultNotice, SectionTitle, selectStyle, type PanelProps,
} from './PanelPrimitives'

const TYPE_SUBS: Record<string, string[]> = {
  武器: ['刀', '剑', '奇门', '搏击', '暗器', '长兵'],
  消耗品: ['丹药', '食物', '心法秘籍', '刀法秘籍', '剑法秘籍', '奇门秘籍', '搏击秘籍', '暗器秘籍', '长兵秘籍', '技艺书', '道具'],
  护甲: [],
  冠巾: [],
  饰品: [],
}

export function BagPanel({ slot, request }: PanelProps) {
  const [type, setType] = useState('')
  const [sub, setSub] = useState('')
  const [bag, setBag] = useState<any>(null)
  const [carry, setCarry] = useState<any>(null)
  const [loading, setLoading] = useState(true)
  const [busy, setBusy] = useState<string | null>(null)
  const [error, setError] = useState('')
  const [notice, setNotice] = useState('')
  const loadSeq = useRef(0)

  const refresh = useCallback(async (showLoading = true) => {
    const seq = ++loadSeq.current
    if (showLoading) setLoading(true)
    setError('')
    const action: Record<string, unknown> = { 类型: '查看背包' }
    if (type) action.筛选类型 = type
    if (type && sub) action.筛选子类型 = sub
    try {
      const response = await request(slot, [action, { 类型: '配置物品' }])
      if (seq !== loadSeq.current) return
      const [nextBag, nextCarry] = response.results
      const err = engineError(nextBag) || engineError(nextCarry)
      if (err) throw new Error(err)
      setBag(nextBag)
      setCarry(nextCarry)
    } catch (caught) {
      if (seq === loadSeq.current) setError(caught instanceof Error ? caught.message : String(caught))
    } finally {
      if (seq === loadSeq.current) setLoading(false)
    }
  }, [request, slot, sub, type])

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
      setNotice(resultNotice(result) || '操作完成')
      await refresh(false)
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : String(caught))
    } finally {
      setBusy(null)
    }
  }

  const subs = TYPE_SUBS[type] || []
  const items = Array.isArray(bag?.物品列表) ? bag.物品列表 : []
  const carried = Array.isArray(carry?.携带道具) ? carry.携带道具 : []
  const available = Array.isArray(carry?.可换道具) ? carry.可换道具 : []

  return (
    <div>

      <div style={{ display: 'flex', alignItems: 'center', gap: 5, flexWrap: 'wrap', marginBottom: 8 }}>
        <span style={{ color: '#9a8c6e', fontSize: 12 }}>类型</span>
        <select style={selectStyle} value={type} disabled={Boolean(busy)} onChange={event => { setType(event.target.value); setSub('') }}>
          <option value="">全部类型</option>
          {Object.keys(TYPE_SUBS).map(value => <option key={value} value={value}>{value}</option>)}
        </select>
        <span style={{ color: '#9a8c6e', fontSize: 12 }}>子类型</span>
        <select style={selectStyle} value={sub} disabled={Boolean(busy) || !type || !subs.length} onChange={event => setSub(event.target.value)}>
          <option value="">全部子类型</option>
          {subs.map(value => <option key={value} value={value}>{value}</option>)}
        </select>
        <PanelButton disabled={loading || Boolean(busy)} onClick={() => void refresh()}>刷新</PanelButton>
      </div>
      <PanelNotice kind="error">{error}</PanelNotice>
      <PanelNotice kind="notice">{notice}</PanelNotice>
      {loading && !bag ? <LoadingState /> : items.length ? (
        <PanelTable
          headers={['名称', '数量', '类型', '品级', '效果', '操作']}
          rows={items.map((item: any) => {
            const usable = /世界|通用/.test(String(item.适用场合 || ''))
            return [
              <b>{displayValue(item.名称)}</b>,
              `×${item.数量 ?? 1}`,
              [item.类型, item.子类型].filter(Boolean).join(' · ') || '—',
              item.品名 || displayValue(item.品级),
              displayValue(item.使用效果),
              usable ? (
                <PanelButton disabled={Boolean(busy)} onClick={() => void act(`use:${item.名称}`, { 类型: '使用物品', 物品: item.名称 })}>
                  {busy === `use:${item.名称}` ? '使用中…' : '使用'}
                </PanelButton>
              ) : '—',
            ]
          })}
        />
      ) : <EmptyState>（背包为空）</EmptyState>}

      <SectionTitle>战斗携带（最多 4 类）</SectionTitle>
      <PanelTable
        headers={['携带中', '数量', '操作']}
        rows={carried.map((item: any) => {
          const name = item?.名称 || item
          return [
            displayValue(name),
            `×${item?.数量 ?? 1}`,
            <PanelButton disabled={Boolean(busy)} danger onClick={() => void act(`remove:${name}`, { 类型: '配置物品', 操作: '卸', 物品: name })}>
              {busy === `remove:${name}` ? '卸下中…' : '卸下'}
            </PanelButton>,
          ]
        })}
      />

      <SectionTitle>可换消耗品</SectionTitle>
      <PanelTable
        headers={['名称', '数量', '操作']}
        rows={available.map((item: any) => {
          const name = item?.名称 || item
          return [
            displayValue(name),
            `×${item?.数量 ?? 1}`,
            <PanelButton disabled={Boolean(busy) || carried.length >= 4} onClick={() => void act(`add:${name}`, { 类型: '配置物品', 操作: '装', 物品: name })}>
              {busy === `add:${name}` ? '装上中…' : '装上'}
            </PanelButton>,
          ]
        })}
      />
    </div>
  )
}
