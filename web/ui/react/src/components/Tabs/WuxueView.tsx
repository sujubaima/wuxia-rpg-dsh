import { useCallback, useEffect, useState } from 'react'
import { fetchUi } from '../../api'
import { useGameStore, useSelectedMember } from '../../store'
import { esc } from '../../lib/markdown'
import { Btn, UiTable } from '../ui'
import { CardShell, DumpJson, LoadingCard } from './CardPanel'
import type { EngineResult } from '../../types'

/** 使用物品按 目标 结算；其余行为按 角色 配置。与 dsh 版语义一致。 */
function withRole(a: { 类型: string } & Record<string, any>, role: string | null) {
  if (!role) return a
  return { ...a, ...(a.类型 === '使用物品' ? { 目标: role } : { 角色: role }) }
}

function skillTable(
  list: any[], kind: 'carried' | 'avail', listD: EngineResult, refresh: () => Promise<void>, carriedCount: number,
  onMastery: (name: string) => void, role: string | null,
) {
  if (!list.length) return <div className="ph">{kind === 'carried' ? '（未携带武学）' : '（无）'}</div>
  const masteryOf: Record<string, any> = {}
  for (const grp of ['主动武学', '心法']) for (const e of ((listD as any)[grp] || [])) masteryOf[e.名称] = e
  return (
    <UiTable
      headers={['名称', '境界', '品级', '威力', '内力', '冷却', '特效', '操作']}
      rows={list.map((w, i) => {
        const carried = kind === 'carried'
        const meta = masteryOf[w.名称] || {}
        const lv = meta.等级 != null ? meta.等级 : w.等级
        const cdRaw = w.冷却
        const cdStr = cdRaw && cdRaw !== 0 && cdRaw !== '无冷却' && cdRaw !== '无' ? ' ｜ 冷却' + cdRaw : ' ｜ 无冷却'
        return [
          <b key={i} dangerouslySetInnerHTML={{ __html: esc(w.名称) }} />,
          lv != null ? `${lv}境` : '', w.品名 || meta.品名 || '',
          w.威力倍率 != null ? '威' + w.威力倍率 : '', w.内力消耗 != null ? '内' + w.内力消耗 : '',
          w.冷却时间 != null ? '冷却' + w.冷却时间 : '',
          <span className="muted" key="e">{esc(w.特效 || w.描述 || '无')}</span>,
          <span key="o">
            {carried ? (
              <Btn onClick={() => useGameStore.getState().uiOp(withRole({ 类型: '配置武学', 操作: '卸', 武学: w.名称 }, role), { refresh })}>卸下</Btn>
            ) : (
              <Btn disabled={carriedCount >= 4} onClick={() => useGameStore.getState().uiOp(withRole({ 类型: '配置武学', 操作: '装', 武学: w.名称 }, role), { refresh })}>装上</Btn>
            )}{' '}
            <Btn onClick={() => onMastery(w.名称)}>精进</Btn>
          </span>,
        ]
      })}
    />
  )
}

function MasteryView({ name, role, onBack }: { name: string; role: string | null; onBack: () => void }) {
  const uiOp = useGameStore(s => s.uiOp)
  const [d, setD] = useState<EngineResult | null>(null)
  const refresh = useCallback(async () => {
    setD(await fetchUi(withRole({ 类型: '武学精进', 武学: name }, role)))
  }, [name, role])
  useEffect(() => { void refresh() }, [refresh])
  if (!d || d.界面 !== 'mastery-ui') return <CardShell title={'精进 · ' + name}>{d ? <DumpJson data={d} /> : null}<Btn onClick={onBack}>返回武学</Btn></CardShell>
  const td: any = d.十境表数据
  return (
    <CardShell title={'精进 · ' + name}>
      <div className="ph">当前 {String(d.等级 ?? '')}境 ｜ 经验值 {String(d.经验值 ?? '')}</div>
      {td ? (
        <div className="mastery">
          <div className="m-head" dangerouslySetInnerHTML={{
            __html: `<span class="m-name">${esc(td.武学 || '')}</span><span class="muted">${esc(td.品级 != null ? '品级' + td.品级 : '品级未定')} ｜ 精进消耗×${td.品级系数 != null ? td.品级系数 : '?'}</span>`,
          }} />
          <UiTable
            headers={['境', '状态', '消耗经验', '增益']}
            rows={((td.十境 || []) as any[]).map((r: any) => [
              r.境,
              <span key="s" className={'m-st ' + (r.已习得 ? 'got' : '')}>{r.已习得 ? '✓' : '✗'}</span>,
              r.境 <= 1 ? '—' : r.消耗经验,
              <span key="e" className="m-eff" dangerouslySetInnerHTML={{
                __html: esc(r.增益 || '') + (r.当前 ? '<span class="m-mark">（当前）</span>' : r.下一境 ? '<span class="m-mark">← 下一境</span>' : ''),
              }} />,
            ])}
          />
          <div className="m-foot">
            {td.当前境 >= 10 ? '已达大成（第 10 境），无可精进之境。' : (
              <span dangerouslySetInnerHTML={{
                __html: `下一境（第 ${td.下一境} 境）需经验 ${td.下一境消耗 != null ? td.下一境消耗 : '?'} ｜ 当前 ${td.经验} ｜ <span class="${td.可精进 ? 'ok' : 'warn'}">${td.可精进 ? '可精进' : '经验不足，暂无法精进'}</span>`,
              }} />
            )}
          </div>
        </div>
      ) : d.十境表 ? <pre className="prebox">{d.十境表 as string}</pre> : null}
      <Btn primary disabled={td && td.可精进 === false} onClick={() => uiOp(withRole({ 类型: '武学精进', 武学: name, 操作: '精进' }, role), { refresh })}>精进一层</Btn>{' '}
      <Btn onClick={onBack}>返回武学</Btn>
    </CardShell>
  )
}

export function WuxueView() {
  const role = useSelectedMember()
  const [d, setD] = useState<EngineResult | null>(null)
  const [listD, setListD] = useState<EngineResult | null>(null)
  const [mastery, setMastery] = useState<string | null>(null)
  const refresh = useCallback(async () => {
    const cfg = await fetchUi(withRole({ 类型: '配置武学' }, role))
    const lst = await fetchUi(role ? { 类型: '武学列表', 角色: role } : { 类型: '武学列表' })
    setD(cfg); setListD(lst)
  }, [role])
  const [curXinfa, setCurXinfa] = useState<string | null>(null)
  const uiOp = useGameStore(s => s.uiOp)
  useEffect(() => { void refresh() }, [refresh])

  if (mastery) return <MasteryView name={mastery} role={role} onBack={() => { setMastery(null); void refresh() }} />
  if (!d) return <LoadingCard title="武学" />
  const err = d?.错误
  const carried = (d?.携带武学 as any[]) || []
  const avail = (d?.可用武学 as any[]) || []
  const xfs = ((listD?.心法 as any[]) || []).map(x => x.名称)
  const resolvedXinfa = curXinfa ?? (d?.运转心法 as string) ?? '无'
  return (
    <CardShell title="武学">
      {err ? <DumpJson data={d} /> : (
        <>
          <div>
            <span className="muted">运转心法：</span>
            <select className="uibtn" value={resolvedXinfa} onChange={e => setCurXinfa(e.target.value)}>
              <option value="无">（不运转）</option>
              {xfs.map(n => <option key={n} value={n}>{n}</option>)}
            </select>{' '}
            <Btn onClick={() => uiOp(withRole({ 类型: '配置武学', 运转心法: resolvedXinfa }, role), { refresh })}>设定</Btn>
            {d?.运转心法特效 ? <div className="muted">{d.运转心法特效 as string}</div> : null}
          </div>
          <h4>携带武学（战斗中可用）</h4>
          {skillTable(carried, 'carried', listD || {}, refresh, carried.length, setMastery, role)}
          <h4>可用武学（已习得未携带）</h4>
          {skillTable(avail, 'avail', listD || {}, refresh, carried.length, setMastery, role)}
        </>
      )}
    </CardShell>
  )
}
