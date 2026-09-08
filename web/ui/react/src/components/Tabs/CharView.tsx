import { useEffect, useState } from 'react'
import { fetchUi } from '../../api'
import { useGameStore } from '../../store'
import { kvGrid, Btn, UiTable } from '../ui'
import { CardShell, DumpJson, LoadingCard } from './CardPanel'
import type { EngineResult } from '../../types'

export function CharView() {
  const lastExpl = useGameStore(s => s.lastExpl)
  const selectedMember = useGameStore(s => s.selectedMember)
  const [d, setD] = useState<EngineResult | null>(null)
  const [name, setName] = useState<string | null>(null)

  const names = (lastExpl?.队伍状态 || []).map(m => m.名称 || '')
  const resolved = (selectedMember && names.includes(selectedMember) ? selectedMember : names[0]) || null

  useEffect(() => {
    if (!resolved) { setD(null); setName(null); return }
    setName(resolved)
    void fetchUi({ 类型: '角色信息', 角色: resolved }).then(setD)
  }, [resolved])

  if (!resolved) {
    return (
      <CardShell title="角色">
        <Btn onClick={() => setD(null)}>重试</Btn>
      </CardShell>
    )
  }
  void name
  const info = d?.角色信息 as any
  if (!info) {
    if (!d) return <LoadingCard title="角色" />
    return <CardShell title="角色"><DumpJson data={d} /></CardShell>
  }
  const base: Record<string, unknown> = {
    名称: info.名称, 性别: info.性别, 年龄: info.年龄, 经验值: info.经验值,
    气血: `${info.气血}/${info.气血上限}`, 内力: `${info.内力}/${info.内力上限}`,
    状态: info.死亡 ? '已死亡' : '健在', 运转心法: info.运转心法 || '无',
  }
  const sections: [string, any][] = [
    ['一级属性', info.一级属性], ['极性', info.极性], ['武艺', info.武艺], ['技艺', info.技艺], ['二级属性', info.二级属性],
  ]
  return (
    <CardShell title="角色">
      {kvGrid(base)}
      {sections.map(([t, o]) => <div key={t}><h4>{t}</h4>{kvGrid(o)}</div>)}
      <h4>携带武学</h4>
      <div className="ph">{((info.携带技能 || []) as string[]).join('、') || '（无）'}</div>
      <h4>战斗携带物品</h4>
      <div className="ph">{((info.携带物品 || []) as any[]).map(i => i.名称 || i).join('、') || '（无）'}</div>
      <h4>装备</h4>
      <UiTable headers={['槽位', '装备']} rows={Object.entries(info.装备 || {}).map(([k, v]) => [k, (v as string) || '（空）'])} />
    </CardShell>
  )
}
