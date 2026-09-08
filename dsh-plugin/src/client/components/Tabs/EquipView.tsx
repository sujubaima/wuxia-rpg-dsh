import { useCallback, useEffect, useState } from 'react'
import { fetchUi } from '../../api'
import { useGameStore } from '../../store'
import { esc } from '../../lib/markdown'
import { Btn, UiTable } from '../ui'
import { CardShell, DumpJson, LoadingCard } from './CardPanel'
import type { EngineResult } from '../../types'

const EQUIP_SLOTS = ['武器1', '武器2', '护甲', '饰品', '冠巾']
const WEAPON_SUBS: Record<string, number> = { 刀: 1, 剑: 1, 奇门: 1, 搏击: 1, 暗器: 1, 长兵: 1 }
const slotOfSub = (sub: string) => ({ 护甲: '护甲', 饰品: '饰品', 冠巾: '冠巾' } as Record<string, string>)[sub] || null

export function EquipView() {
  const uiOp = useGameStore(s => s.uiOp)
  const [d, setD] = useState<EngineResult | null>(null)
  const refresh = useCallback(async () => { setD(await fetchUi({ 类型: '配置装备' })) }, [])
  useEffect(() => { void refresh() }, [refresh])
  const err = d?.错误
  const cur = (d?.当前装备 || {}) as Record<string, string>
  const avail = (d?.可换装备 as any[]) || []
  if (!d) return <LoadingCard title="装备" />
  return (
    <CardShell title="装备" desc="穿上/卸下即时生效，回执见游历流系统行。">
      {err ? <DumpJson data={d} /> : (
        <>
          <div className="slotrow">
            {EQUIP_SLOTS.map(s => (
              <div className="slotcard" key={s}>
                <div className="sl">{s}</div>
                <div className="eq">{cur[s] || '（空）'}</div>
                {cur[s] && <Btn onClick={() => uiOp({ 类型: '配置装备', 操作: '脱', 槽位: s }, { refresh })}>卸下</Btn>}
              </div>
            ))}
          </div>
          <h4>物品栏可换装备</h4>
          {avail.length === 0 ? <div className="ph">（无可换装备）</div> : (
            <UiTable
              headers={['名称', '类型', '品级', '操作']}
              rows={avail.map(it => {
                const isWeapon = it.类型 === '武器' || WEAPON_SUBS[it.子类型]
                const ops = isWeapon ? (
                  <span key="w">
                    <Btn onClick={() => uiOp({ 类型: '配置装备', 操作: '穿', 槽位: '武器1', 物品: it.名称 }, { refresh })}>装到武器1</Btn>{' '}
                    <Btn onClick={() => uiOp({ 类型: '配置装备', 操作: '穿', 槽位: '武器2', 物品: it.名称 }, { refresh })}>装到武器2</Btn>
                  </span>
                ) : (() => {
                  const sl = it.类型 && EQUIP_SLOTS.includes(it.类型) ? it.类型 : slotOfSub(it.子类型)
                  return <Btn key="p" disabled={!sl} onClick={() => sl && uiOp({ 类型: '配置装备', 操作: '穿', 槽位: sl, 物品: it.名称 }, { refresh })}>穿上</Btn>
                })()
                return [
                  <b key="n" dangerouslySetInnerHTML={{ __html: esc(it.名称) }} />,
                  (it.类型 || '') + (it.子类型 ? '·' + it.子类型 : ''), it.品名 || '', ops,
                ]
              })}
            />
          )}
        </>
      )}
    </CardShell>
  )
}
