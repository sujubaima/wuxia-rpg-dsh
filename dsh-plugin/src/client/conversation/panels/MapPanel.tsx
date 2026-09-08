import { useCallback, useEffect, useState } from 'react'
import { renderSceneSvg } from '../../lib/sceneGraph'
import {
  displayValue, EmptyState, engineError, LoadingState, PanelButton,
  PanelNotice, PanelTable, SectionTitle, type PanelProps,
} from './PanelPrimitives'

export function MapPanel({ slot, request }: PanelProps) {
  const [data, setData] = useState<any>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')

  const refresh = useCallback(async () => {
    setLoading(true)
    setError('')
    try {
      const response = await request(slot, [{ 类型: '查看地图' }])
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

  let svg = ''
  try {
    if (data?.场景图 && data?.当前场景) {
      svg = renderSceneSvg(data.场景图, String(data.当前场景), data.驿站出口 ? String(data.驿站出口) : undefined)
    }
  } catch { /* 退回文本邻接图 */ }
  const places = Array.isArray(data?.已知地点) ? data.已知地点 : []

  return (
    <div>

      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', gap: 8 }}>
        <div style={{ color: '#9a8c6e', fontSize: 12, lineHeight: 1.5 }}>
          当前区域：<span style={{ color: '#e8dcc4' }}>{displayValue(data?.当前区域)}</span><br />
          当前场景：<span style={{ color: '#e8dcc4' }}>{displayValue(data?.当前场景)}</span>
        </div>
        <PanelButton disabled={loading} onClick={() => void refresh()}>刷新</PanelButton>
      </div>
      <PanelNotice kind="error">{error}</PanelNotice>
      {loading && !data ? <LoadingState /> : (
        <>
          <SectionTitle>区域场景图</SectionTitle>
          {svg ? (
            <div
              style={{ padding: 9, overflowX: 'auto', background: '#0c0a07', border: '1px solid #3a2f22', borderRadius: 7 }}
              dangerouslySetInnerHTML={{ __html: svg }}
            />
          ) : data?.邻接图 ? (
            <pre style={{ padding: 9, margin: 0, color: '#ddd0b8', background: '#0f0d0a', border: '1px solid #3a2f22', borderRadius: 6, whiteSpace: 'pre-wrap', fontSize: 11.5 }}>{String(data.邻接图)}</pre>
          ) : <EmptyState>（当前区域没有场景图）</EmptyState>}
          <SectionTitle>已知地点</SectionTitle>
          <PanelTable
            headers={['名称', '标记']}
            rows={places.map((place: any) => [
              displayValue(place.名称),
              Array.isArray(place.标记) && place.标记.length ? (
                <span>{place.标记.map((tag: unknown, index: number) => <span key={index} style={{ display: 'inline-block', margin: '0 4px 2px 0', padding: '1px 6px', color: '#c8a456', border: '1px solid #6f5527', borderRadius: 10 }}>{displayValue(tag)}</span>)}</span>
              ) : '—',
            ])}
          />
        </>
      )}
    </div>
  )
}
