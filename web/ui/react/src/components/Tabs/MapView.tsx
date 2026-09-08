import { useEffect, useState } from 'react'
import { fetchUi } from '../../api'
import { esc } from '../../lib/markdown'
import { renderSceneSvg } from '../../lib/sceneGraph'
import { UiTable } from '../ui'
import { CardShell, DumpJson, LoadingCard } from './CardPanel'
import type { EngineResult } from '../../types'

export function MapView() {
  const [d, setD] = useState<EngineResult | null>(null)
  useEffect(() => { void fetchUi({ 类型: '查看地图' }).then(setD) }, [])
  if (!d) return <LoadingCard title="地图" />
  if (d.界面 !== 'map-ui') return <CardShell title="地图"><DumpJson data={d} /></CardShell>
  const svg = d.场景图 && d.当前场景 ? renderSceneSvg(d.场景图 as any, d.当前场景 as string, d.驿站出口 as string) : null
  const places = (d.已知地点 as any[]) || []
  return (
    <CardShell title="地图">
      <div className="ph">当前区域：{d.当前区域 as string} ｜ 当前场景：{(d.当前场景 as string) || '—'} ｜ 驿站出口：{(d.驿站出口 as string) || '—'}</div>
      {svg ? (
        <div style={{ background: '#0c0a07', border: '1px solid #3a2f22', borderRadius: 8, padding: 10, overflowX: 'auto' }}
          dangerouslySetInnerHTML={{ __html: svg }} />
      ) : d.邻接图 ? (
        <>
          <h4>邻接图（场景图不可用，退化引擎文本）</h4>
          <pre className="prebox">{d.邻接图 as string}</pre>
        </>
      ) : null}
      <h4>已知地点</h4>
      {places.length ? (
        <UiTable headers={['名称', '标记']} rows={places.map(p => [
          p.名称,
          <span key="t" dangerouslySetInnerHTML={{ __html: ((p.标记 || []) as string[]).map(t => `<span class="tag">${esc(t)}</span>`).join('') }} />,
        ])} />
      ) : <div className="ph">（仅当前场景）</div>}
    </CardShell>
  )
}
