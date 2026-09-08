import { memo, useEffect, useRef } from 'react'
import { useGameStore } from '../../store'
import { Markdown } from '../Markdown'
import { renderInline } from '../../lib/markdown'
import type { ChatMessage } from '../../types'

const MessageItem = memo(function MessageItem({ m }: { m: ChatMessage }) {
  return (
    <div className={'row ' + m.role}>
      <div className="avatar">{m.role === 'user' ? '侠' : 'GM'}</div>
      {m.role === 'user' ? (
        <div className="bubble" dangerouslySetInnerHTML={{ __html: renderInline(m.text || '') }} />
      ) : (
        <div className="bubble">
          {(m.segs || []).map((s, i) =>
            s.kind === 'text' ? (
              <div className="md" key={i}>
                <Markdown text={s.text} />
              </div>
            ) : (
              <div className="tools" key={i}>
                <span className="tool">◆ 运算：{s.name}</span>
              </div>
            ),
          )}
        </div>
      )}
    </div>
  )
})

export function TravelLog() {
  const messages = useGameStore(s => s.messages)
  const ref = useRef<HTMLDivElement>(null)
  useEffect(() => {
    if (ref.current) ref.current.scrollTop = ref.current.scrollHeight
  }, [messages])
  return (
    <details id="travelLog">
      <summary></summary>
      <div id="msgs" ref={ref}>
        {messages.map((m, i) => <MessageItem key={i} m={m} />)}
      </div>
    </details>
  )
}
