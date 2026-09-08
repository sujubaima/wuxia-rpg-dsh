import { useEffect, useState } from 'react'
import { fetchUi } from '../../api'
import { CardShell, DumpJson, LoadingCard } from './CardPanel'
import type { EngineResult } from '../../types'

export function ClueView() {
  const [d, setD] = useState<EngineResult | null>(null)
  useEffect(() => { void fetchUi({ 类型: '查看线索' }).then(setD) }, [])
  if (!d) return <LoadingCard title="线索" />
  if (d.界面 !== 'clue-ui') return <CardShell title="线索"><DumpJson data={d} /></CardShell>
  const sections: [string, any[], boolean][] = [
    ['进行中', (d.进行中 as any[]) || [], true],
    ['已关闭', (d.已关闭 as any[]) || [], false],
  ]
  const summary = typeof d.经历概括 === 'string' ? d.经历概括.trim() : ''
  return (
    <CardShell title="线索">
      {summary ? (
        <details style={{ marginBottom: 10 }}>
          <summary style={{ cursor: 'pointer', fontWeight: 600 }}>经历概括</summary>
          <div className="clue-summary">{summary}</div>
        </details>
      ) : null}
      {sections.map(([title, arr, defaultOpen]) => (
        <details key={title} open={defaultOpen} style={{ marginBottom: 8 }}>
          <summary style={{ cursor: 'pointer', fontWeight: 600 }}>{title}{arr.length ? `（${arr.length}）` : ''}</summary>
          <div style={{ marginTop: 6 }}>
            {!arr.length ? <div className="ph">（无）</div> : arr.map((cl, i) => (
              <div key={i} style={{ marginBottom: 9 }}>
                <div className="tag">{cl.名称}</div>
                {(cl.进展节点 || []).map((n: any, j: number) => (
                  <div className="clue-node" key={j}>
                    {n.描述 || ''}
                    {n.奖励 && <div className="rw">奖励：{n.奖励}</div>}
                  </div>
                ))}
              </div>
            ))}
          </div>
        </details>
      ))}
    </CardShell>
  )
}
