import { useCallback, useEffect, useState } from 'react'
import {
  displayValue, EmptyState, engineError, KeyValueGrid, LoadingState, PanelButton,
  PanelNotice, PanelTable, SectionTitle, type PanelProps,
} from './PanelPrimitives'

export function CharacterPanel({ slot, request, members }: PanelProps) {
  const [selected, setSelected] = useState(() => members[0] || '')
  const [data, setData] = useState<any>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')

  useEffect(() => {
    if (!members.includes(selected)) setSelected(members[0] || '')
  }, [members, selected])

  const refresh = useCallback(async () => {
    if (!selected) {
      setData(null)
      setError('当前队伍没有可查询角色')
      setLoading(false)
      return
    }
    setLoading(true)
    setError('')
    try {
      const response = await request(slot, [{ 类型: '角色信息', 角色: selected }])
      const next = response.results[0]
      const err = engineError(next)
      if (err) throw new Error(err)
      setData(next)
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : String(caught))
    } finally {
      setLoading(false)
    }
  }, [request, selected, slot])

  useEffect(() => { void refresh() }, [refresh])

  const info = data?.角色信息
  const base = info ? {
    名称: info.名称,
    性别: info.性别,
    年龄: info.年龄,
    经验值: info.经验值,
    气血: `${info.气血 ?? '—'}/${info.气血上限 ?? '—'}`,
    内力: `${info.内力 ?? '—'}/${info.内力上限 ?? '—'}`,
    状态: info.死亡 ? '已死亡' : '健在',
    运转心法: info.运转心法 || '无',
  } : null
  const carriedItems = Array.isArray(info?.携带物品) ? info.携带物品 : []
  const equipment = info?.装备 && typeof info.装备 === 'object' ? info.装备 : {}

  return (
    <div>

      <div style={{ display: 'flex', alignItems: 'center', gap: 4, flexWrap: 'wrap' }}>
        {members.map(name => (
          <PanelButton key={name} active={selected === name} disabled={loading && selected === name} onClick={() => setSelected(name)}>{name}</PanelButton>
        ))}
        <span style={{ flex: 1 }} />
        <PanelButton disabled={loading || !selected} onClick={() => void refresh()}>刷新</PanelButton>
      </div>
      <PanelNotice kind="error">{error}</PanelNotice>
      {loading && !info ? <LoadingState /> : info ? (
        <>
          <SectionTitle>基础信息</SectionTitle>
          <KeyValueGrid data={base} />
          {([
            ['一级属性', info.一级属性],
            ['极性', info.极性],
            ['武艺', info.武艺],
            ['技艺', info.技艺],
            ['二级属性', info.二级属性],
          ] as [string, Record<string, unknown>][]).map(([title, values]) => (
            <div key={title}>
              <SectionTitle>{title}</SectionTitle>
              <KeyValueGrid data={values} />
            </div>
          ))}
          <SectionTitle>携带武学</SectionTitle>
          <EmptyState>{Array.isArray(info.携带技能) && info.携带技能.length ? info.携带技能.map(displayValue).join('、') : '（无）'}</EmptyState>
          <SectionTitle>战斗携带物品</SectionTitle>
          <PanelTable
            headers={['名称', '数量']}
            rows={carriedItems.map((item: any) => [displayValue(item?.名称 || item), item?.数量 != null ? `×${item.数量}` : '—'])}
          />
          <SectionTitle>装备</SectionTitle>
          <PanelTable headers={['槽位', '装备']} rows={Object.entries(equipment).map(([key, value]) => [key, displayValue(value)])} />
        </>
      ) : <EmptyState>（暂无角色信息）</EmptyState>}
    </div>
  )
}
