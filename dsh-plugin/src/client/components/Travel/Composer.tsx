import { useRef } from 'react'
import { useGameStore } from '../../store'

export function Composer() {
  const draft = useGameStore(s => s.composerDraft)
  const setDraft = useGameStore(s => s.setComposerDraft)
  const send = useGameStore(s => s.send)
  const busy = useGameStore(s => s.busy)
  const taRef = useRef<HTMLTextAreaElement>(null)

  const autosize = () => {
    const ta = taRef.current
    if (!ta) return
    ta.style.height = 'auto'
    ta.style.height = Math.min(ta.scrollHeight, 160) + 'px'
  }

  const submit = () => {
    const msg = draft.trim()
    if (!msg || busy) return
    setDraft('')
    if (taRef.current) taRef.current.style.height = 'auto'
    void send(msg)
  }

  return (
    <footer id="composer">
      <form id="form" onSubmit={e => { e.preventDefault(); submit() }}>
        <textarea
          id="input"
          ref={taRef}
          placeholder="落字成令…（Enter 发送，Shift+Enter 换行）"
          rows={1}
          value={draft}
          onChange={e => { setDraft(e.target.value); autosize() }}
          onKeyDown={e => { if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); submit() } }}
        />
        <button id="send" type="submit" disabled={busy}>送出</button>
      </form>
      <div className="status" id="status">
        {busy ? <span className="dot">●</span> : null}
        {busy ? ' 正在运笔…' : ''}
      </div>
    </footer>
  )
}
