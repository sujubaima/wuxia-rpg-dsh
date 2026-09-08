import { useCallback, useEffect, useState } from 'react'
import { fetchUi } from '../../api'
import { useGameStore } from '../../store'
import { effText } from '../../lib/format'
import { esc } from '../../lib/markdown'
import { Btn, UiTable } from '../ui'
import { CardShell, DumpJson, LoadingCard } from './CardPanel'
import type { EngineResult } from '../../types'

const TYPE_SUBS: Record<string, string[]> = {
  武器: ['刀', '剑', '奇门', '搏击', '暗器', '长兵'],
  消耗品: ['丹药', '食物', '心法秘籍', '刀法秘籍', '剑法秘籍', '奇门秘籍', '搏击秘籍', '暗器秘籍', '长兵秘籍', '技艺书', '道具'],
  护甲: [], 冠巾: [], 饰品: [],
}

export function BagView() {
  const uiOp = useGameStore(s => s.uiOp)
  const [type, setType] = useState('')
  const [sub, setSub] = useState('')
  const [bag, setBag] = useState<EngineResult | null>(null)
  const [carry, setCarry] = useState<EngineResult | null>(null)

  const refresh = useCallback(async () => {
    const a: any = { 类型: '查看背包' }
    if (type) a.筛选类型 = type
    if (type && sub) a.筛选子类型 = sub
    setBag(await fetchUi(a))
    setCarry(await fetchUi({ 类型: '配置物品' }))
  }, [type, sub])

  useEffect(() => { void refresh() }, [refresh])

  const subs = TYPE_SUBS[type] || []
  const items = (bag?.物品列表 as any[]) || []
  const err = bag?.错误
  const carryItems = (carry?.携带道具 as any[]) || []
  const swapItems = (carry?.可换道具 as any[]) || []

  if (!bag) return <LoadingCard title="物品" />
  return (
    <CardShell title="物品">
      <div style={{ margin: '0 0 8px' }}>
        <span className="muted">类型 </span>
        <select className="uibtn" value={type} onChange={e => { setType(e.target.value); setSub('') }}>
          <option value="">全部类型</option>
          {['武器', '消耗品', '护甲', '冠巾', '饰品'].map(t => <option key={t} value={t}>{t}</option>)}
        </select>
        <span className="muted"> 子类型 </span>
        <select className="uibtn" value={sub} disabled={!type || subs.length === 0} onChange={e => setSub(e.target.value)}>
          <option value="">全部子类型</option>
          {subs.map(s => <option key={s} value={s}>{s}</option>)}
        </select>{' '}
        <Btn onClick={() => void refresh()}>查询</Btn>
      </div>
      {err ? <DumpJson data={bag} /> : items.length ? (
        <UiTable
          headers={['名称', '数量', '类型', '子类型', '品级', '效果', '操作']}
          rows={items.map(it => {
            const usable = /世界|通用/.test(it.适用场合 || '')
            return [
              <b key="n" dangerouslySetInnerHTML={{ __html: esc(it.名称) }} />,
              '×' + (it.数量 ?? 1), it.类型 || '', it.子类型 || '', it.品名 || '',
              <span className="muted" key="e">{esc(effText(it.使用效果))}</span>,
              usable ? <Btn key="u" onClick={() => uiOp({ 类型: '使用物品', 物品: it.名称 }, { refresh })}>使用</Btn> : null,
            ]
          })}
        />
      ) : <div className="ph">（空）</div>}
      <h4>战斗携带（≤4类，战斗内可用消耗品）</h4>
      {!carry || carry.界面 !== 'item-ui' ? (
        <div className="ph">（查询战斗携带失败或为空）</div>
      ) : (
        <>
          <UiTable
            headers={['携带中', '数量', '']}
            rows={carryItems.map(it => [
              it.名称 || it, '×' + (it.数量 ?? 1),
              <Btn key="x" onClick={() => uiOp({ 类型: '配置物品', 操作: '卸', 物品: it.名称 || it }, { refresh })}>卸下</Btn>,
            ])}
          />
          {swapItems.length > 0 && (
            <>
              <h4>物品栏可换消耗品</h4>
              <UiTable
                headers={['名称', '数量', '']}
                rows={swapItems.map(it => [
                  it.名称 || it, '×' + (it.数量 ?? 1),
                  <Btn key="a" onClick={() => uiOp({ 类型: '配置物品', 操作: '装', 物品: it.名称 || it }, { refresh })}>装上</Btn>,
                ])}
              />
            </>
          )}
        </>
      )}
    </CardShell>
  )
}
