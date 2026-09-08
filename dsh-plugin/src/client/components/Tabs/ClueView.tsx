import { useEffect, useState } from 'react'
import { fetchUi } from '../../api'
import { CardShell, DumpJson, LoadingCard } from './CardPanel'
import type { EngineResult } from '../../types'

export function ClueView() {
  const [d, setD] = useState<EngineResult | null>(null)
  useEffect(() => { void fetchUi({ 类型: '查看线索' }).then(setD) }, [])
  if (!d) return <LoadingCard title="线索" />
  if (d.界面 !== 'clue-ui') return <CardShell title="线索"><DumpJson data={d} /></CardShell>
  const sections: [string, any[]][] = [['进行中', (d.进行中 as any[]) || []], ['已关闭', (d.已关闭 as any[]) || []]]
  return (
    <CardShell title="线索" desc="剧情线索与进展节点；推进请回游历流。">
      {sections.map(([title, arr]) => (
        <div key={title}>
          <h4>{title}</h4>
          {!arr.length ? <div className="ph">（无）</div> : arr.map((cl, i) => (
            <div key={i}>
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
      ))}
    </CardShell>
  )
}
