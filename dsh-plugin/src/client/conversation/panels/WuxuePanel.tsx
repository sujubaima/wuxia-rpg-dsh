import { useCallback, useEffect, useMemo, useState } from 'react'
import {
  displayValue, EmptyState, engineError, LoadingState, PanelButton,
  PanelNotice, PanelTable, resultNotice, SectionTitle, selectStyle, type PanelProps,
} from './PanelPrimitives'

function MasteryPanel({ slot, request, name, onBack }: PanelProps & { name: string; onBack: () => void }) {
  const [data, setData] = useState<any>(null)
  const [loading, setLoading] = useState(true)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const [notice, setNotice] = useState('')

  const refresh = useCallback(async () => {
    setLoading(true)
    setError('')
    try {
      const response = await request(slot, [{ 类型: '武学精进', 武学: name }])
      const next = response.results[0]
      const err = engineError(next)
      if (err) throw new Error(err)
      setData(next)
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : String(caught))
    } finally {
      setLoading(false)
    }
  }, [name, request, slot])

  useEffect(() => { void refresh() }, [refresh])

  const advance = async () => {
    if (busy) return
    setBusy(true)
    setError('')
    setNotice('')
    try {
      const response = await request(slot, [{ 类型: '武学精进', 武学: name, 操作: '精进' }])
      const result = response.results[0]
      const err = engineError(result)
      if (err) throw new Error(err)
      setNotice(resultNotice(result) || '武学已精进')
      await refresh()
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : String(caught))
    } finally {
      setBusy(false)
    }
  }

  const table = data?.十境表数据
  const rows = Array.isArray(table?.十境) ? table.十境 : []
  return (
    <div>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', gap: 8 }}>
        <div>
          <div style={{ color: '#c8a456', fontSize: 14, fontWeight: 600 }}>精进 · {name}</div>
          <div style={{ color: '#9a8c6e', fontSize: 12, marginTop: 3 }}>当前 {data?.等级 ?? '—'} 境 · 经验值 {data?.经验值 ?? '—'}</div>
        </div>
        <PanelButton disabled={busy} onClick={onBack}>返回武学</PanelButton>
      </div>
      <PanelNotice kind="error">{error}</PanelNotice>
      <PanelNotice kind="notice">{notice}</PanelNotice>
      {loading && !data ? <LoadingState /> : table ? (
        <>
          <div style={{ margin: '10px 0 6px', color: '#9a8c6e', fontSize: 12 }}>
            {table.武学 || name} · {table.品级 != null ? `品级 ${table.品级}` : '品级未定'} · 精进消耗 ×{table.品级系数 ?? '?'}
          </div>
          <PanelTable
            headers={['境', '状态', '消耗经验', '增益']}
            rows={rows.map((row: any) => [
              row.境,
              row.已习得 ? <span style={{ color: '#8fb474' }}>✓ 已习得</span> : row.下一境 ? <span style={{ color: '#e0b968' }}>下一境</span> : '未习得',
              Number(row.境) <= 1 ? '—' : displayValue(row.消耗经验),
              <span style={{ color: row.当前 || row.下一境 ? '#e8dcc4' : '#9a8c6e' }}>{displayValue(row.增益)}{row.当前 ? '（当前）' : ''}</span>,
            ])}
          />
          <div style={{ margin: '9px 0', color: table.可精进 ? '#8fb474' : '#c69a70', fontSize: 12 }}>
            {table.当前境 >= 10
              ? '已达第 10 境，无可精进之境。'
              : `下一境：第 ${table.下一境} 境，需经验 ${table.下一境消耗 ?? '?'}；当前 ${table.经验 ?? data?.经验值 ?? '—'}。${table.可精进 ? '可精进。' : '经验不足。'}`}
          </div>
          <PanelButton active disabled={busy || table.当前境 >= 10 || table.可精进 === false} onClick={() => void advance()}>
            {busy ? '精进中…' : '精进一层'}
          </PanelButton>
        </>
      ) : data?.十境表 ? (
        <>
          <pre style={{ padding: 9, borderRadius: 6, background: '#0f0d0a', border: '1px solid #3a2f22', color: '#ddd0b8', whiteSpace: 'pre-wrap', fontSize: 11.5, lineHeight: 1.55 }}>{String(data.十境表)}</pre>
          <PanelButton active disabled={busy} onClick={() => void advance()}>{busy ? '精进中…' : '精进一层'}</PanelButton>
        </>
      ) : <EmptyState>（暂无精进数据）</EmptyState>}
    </div>
  )
}

function SkillTable({
  skills, carried, carriedCount, metadata, busy, onToggle, onMastery,
}: {
  skills: any[]
  carried: boolean
  carriedCount: number
  metadata: Record<string, any>
  busy: string | null
  onToggle: (name: string, operation: '装' | '卸') => void
  onMastery: (name: string) => void
}) {
  return (
    <PanelTable
      headers={['名称', '境界', '品级', '威力/消耗', '特效', '操作']}
      rows={skills.map(skill => {
        const meta = metadata[skill.名称] || {}
        const name = String(skill.名称 || '')
        return [
          <b>{name || '—'}</b>,
          `${meta.等级 ?? skill.等级 ?? '—'} 境`,
          skill.品名 || meta.品名 || displayValue(skill.品级),
          [
            skill.威力倍率 != null ? `威 ${skill.威力倍率}` : '',
            skill.内力消耗 != null ? `内 ${skill.内力消耗}` : '',
            skill.冷却时间 ? `冷却 ${skill.冷却时间}` : '无冷却',
          ].filter(Boolean).join(' · '),
          skill.特效 || skill.描述 || '无',
          <span style={{ whiteSpace: 'nowrap' }}>
            <PanelButton
              danger={carried}
              disabled={Boolean(busy) || (!carried && carriedCount >= 4)}
              onClick={() => onToggle(name, carried ? '卸' : '装')}
            >
              {busy === `toggle:${name}` ? '处理中…' : carried ? '卸下' : '装上'}
            </PanelButton>
            <PanelButton disabled={Boolean(busy)} onClick={() => onMastery(name)}>精进</PanelButton>
          </span>,
        ]
      })}
    />
  )
}

export function WuxuePanel(props: PanelProps) {
  const { slot, request, members } = props
  const mainName = members[0] || ''
  const [config, setConfig] = useState<any>(null)
  const [listData, setListData] = useState<any>(null)
  const [selectedXinfa, setSelectedXinfa] = useState<string | null>(null)
  const [mastery, setMastery] = useState<string | null>(null)
  const [loading, setLoading] = useState(true)
  const [busy, setBusy] = useState<string | null>(null)
  const [error, setError] = useState('')
  const [notice, setNotice] = useState('')

  const refresh = useCallback(async (showLoading = true) => {
    if (!mainName) {
      setError('当前队伍没有可查询角色')
      setLoading(false)
      return
    }
    if (showLoading) setLoading(true)
    setError('')
    try {
      const response = await request(slot, [
        { 类型: '配置武学' },
        { 类型: '武学列表', 角色: mainName },
      ])
      const [nextConfig, nextList] = response.results
      const err = engineError(nextConfig) || engineError(nextList)
      if (err) throw new Error(err)
      setConfig(nextConfig)
      setListData(nextList)
      setSelectedXinfa(null)
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : String(caught))
    } finally {
      setLoading(false)
    }
  }, [mainName, request, slot])

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
      setNotice(resultNotice(result) || '武学配置已更新')
      await refresh(false)
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : String(caught))
    } finally {
      setBusy(null)
    }
  }

  const metadata = useMemo(() => {
    const out: Record<string, any> = {}
    for (const group of ['主动武学', '心法']) {
      for (const entry of Array.isArray(listData?.[group]) ? listData[group] : []) out[entry.名称] = entry
    }
    return out
  }, [listData])

  if (mastery) {
    return <MasteryPanel {...props} name={mastery} onBack={() => { setMastery(null); void refresh(false) }} />
  }

  const carried = Array.isArray(config?.携带武学) ? config.携带武学 : []
  const available = Array.isArray(config?.可用武学) ? config.可用武学 : []
  const xinfas = (Array.isArray(listData?.心法) ? listData.心法 : []).map((entry: any) => String(entry.名称 || '')).filter(Boolean)
  const resolvedXinfa = selectedXinfa ?? String(config?.运转心法 || '无')

  return (
    <div>

      <div style={{ display: 'flex', alignItems: 'center', gap: 6, flexWrap: 'wrap' }}>
        <span style={{ color: '#9a8c6e', fontSize: 12 }}>运转心法</span>
        <select style={selectStyle} value={resolvedXinfa} disabled={Boolean(busy)} onChange={event => setSelectedXinfa(event.target.value)}>
          <option value="无">（不运转）</option>
          {xinfas.map((name: string) => <option key={name} value={name}>{name}</option>)}
        </select>
        <PanelButton disabled={loading || Boolean(busy)} onClick={() => void act('xinfa', { 类型: '配置武学', 运转心法: resolvedXinfa })}>
          {busy === 'xinfa' ? '设定中…' : '设定'}
        </PanelButton>
        <PanelButton disabled={loading || Boolean(busy)} onClick={() => void refresh()}>刷新</PanelButton>
      </div>
      {config?.运转心法特效 ? <div style={{ marginTop: 5, color: '#9a8c6e', fontSize: 12 }}>{String(config.运转心法特效)}</div> : null}
      <PanelNotice kind="error">{error}</PanelNotice>
      <PanelNotice kind="notice">{notice}</PanelNotice>
      {loading && !config ? <LoadingState /> : (
        <>
          <SectionTitle>携带武学（战斗中可用）</SectionTitle>
          {carried.length ? (
            <SkillTable skills={carried} carried carriedCount={carried.length} metadata={metadata} busy={busy} onMastery={setMastery} onToggle={(name, operation) => void act(`toggle:${name}`, { 类型: '配置武学', 操作: operation, 武学: name })} />
          ) : <EmptyState>（未携带武学）</EmptyState>}
          <SectionTitle>可用武学（已习得未携带）</SectionTitle>
          {available.length ? (
            <SkillTable skills={available} carried={false} carriedCount={carried.length} metadata={metadata} busy={busy} onMastery={setMastery} onToggle={(name, operation) => void act(`toggle:${name}`, { 类型: '配置武学', 操作: operation, 武学: name })} />
          ) : <EmptyState>（无）</EmptyState>}
        </>
      )}
    </div>
  )
}
