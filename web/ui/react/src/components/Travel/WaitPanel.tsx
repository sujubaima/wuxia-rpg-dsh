import { useEffect, useRef, useState } from 'react'
import { useGameStore } from '../../store'
import type { WaitLine } from '../../types'

function WaitLineRow({ l }: { l: WaitLine }) {
  const [show, setShow] = useState(false)
  if (l.detail) {
    return (
      <div className="wait-line">
        <span className="wait-summary" style={{ cursor: 'pointer' }} onClick={() => setShow(s => !s)}>
          {l.summary}
        </span>
        <pre className="wait-detail" style={{ display: show ? 'block' : 'none' }}>{l.detail}</pre>
      </div>
    )
  }
  return <div className="wait-line">{l.summary}</div>
}

export function WaitPanel() {
  const steps = useGameStore(s => s.steps)
  const waitLines = useGameStore(s => s.waitLines)
  const logRef = useRef<HTMLDivElement>(null)
  useEffect(() => {
    if (logRef.current) logRef.current.scrollTop = logRef.current.scrollHeight
  }, [waitLines])
  if (steps <= 0) return <div id="waitPanel"></div>
  return (
    <div id="waitPanel" className="show">
      <div className="wait-log" ref={logRef}>
        {waitLines.map(l => <WaitLineRow key={l.id} l={l} />)}
      </div>
    </div>
  )
}
