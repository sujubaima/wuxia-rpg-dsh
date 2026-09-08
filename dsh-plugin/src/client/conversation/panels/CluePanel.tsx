import { useCallback, useEffect, useState } from 'react'
import {
  EmptyState, engineError, LoadingState, PanelButton,
  PanelNotice, type PanelProps,
} from './PanelPrimitives'

function ClueSection({ title, clues, defaultOpen = false }: { title: string; clues: any[]; defaultOpen?: boolean }) {
  return (
    <details open={defaultOpen} style={{ marginBottom: 8 }}>
      <summary style={{ cursor: 'pointer', color: '#c8a456', fontWeight: 600, letterSpacing: 2 }}>
        {title}{clues.length ? `（${clues.length}）` : ''}
      </summary>
      <div style={{ marginTop: 6 }}>
        {!clues.length ? <EmptyState /> : clues.map((clue, index) => (
          <div key={index} style={{ marginBottom: 9, padding: '8px 9px', background: '#17130f', border: '1px solid #3a2f22', borderRadius: 7 }}>
            <div style={{ color: '#d9bd78', fontWeight: 600, marginBottom: 6 }}>{String(clue.名称 || '未命名线索')}</div>
            {Array.isArray(clue.进展节点) && clue.进展节点.length ? clue.进展节点.map((node: any, nodeIndex: number) => (
              <div key={nodeIndex} style={{ position: 'relative', marginLeft: 5, padding: '3px 4px 7px 13px', color: '#ddd0b8', borderLeft: '1px solid #5b4728', fontSize: 12, lineHeight: 1.55 }}>
                <span style={{ position: 'absolute', left: -4, top: 8, width: 7, height: 7, borderRadius: '50%', background: '#9e7937' }} />
                {String(node.描述 || '（暂无描述）')}
                {node.奖励 ? <div style={{ marginTop: 3, color: '#8fb474' }}>奖励：{String(node.奖励)}</div> : null}
              </div>
            )) : <div style={{ color: '#9a8c6e', fontSize: 12 }}>（尚无进展节点）</div>}
          </div>
        ))}
      </div>
    </details>
  )
}

export function CluePanel({ slot, request }: PanelProps) {
  const [data, setData] = useState<any>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')

  const refresh = useCallback(async () => {
    setLoading(true)
    setError('')
    try {
      const response = await request(slot, [{ 类型: '查看线索' }])
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

  return (
    <div>
      <div style={{ display: 'flex', justifyContent: 'flex-end' }}>
        <PanelButton disabled={loading} onClick={() => void refresh()}>刷新</PanelButton>
      </div>
      <PanelNotice kind="error">{error}</PanelNotice>
      {loading && !data ? <LoadingState /> : (
        <>
          {typeof data?.经历概括 === 'string' && data.经历概括.trim() ? (
            <details style={{ marginBottom: 10 }}>
              <summary style={{ cursor: 'pointer', color: '#c8a456', fontWeight: 600 }}>经历概括</summary>
              <div style={{ marginTop: 6, padding: '8px 9px', background: '#17130f', border: '1px solid #3a2f22', borderRadius: 7, color: '#ddd0b8', fontSize: 12, lineHeight: 1.7, whiteSpace: 'pre-wrap' }}>
                {data.经历概括}
              </div>
            </details>
          ) : null}
          <ClueSection title="进行中" clues={Array.isArray(data?.进行中) ? data.进行中 : []} defaultOpen />
          <ClueSection title="已关闭" clues={Array.isArray(data?.已关闭) ? data.已关闭 : []} />
        </>
      )}
    </div>
  )
}
