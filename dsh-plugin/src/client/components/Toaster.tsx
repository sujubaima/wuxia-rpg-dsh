import { useEffect, useState } from 'react'
import { useGameStore } from '../store'

export function Toaster() {
  const toasts = useGameStore(s => s.toasts)
  return (
    <div id="toastWrap">
      {toasts.map(t => (
        <Toast key={t.id} id={t.id} text={t.text} cls={t.cls} />
      ))}
    </div>
  )
}

function Toast({ id, text, cls }: { id: number; text: string; cls?: string }) {
  const [shown, setShown] = useState(false)
  useEffect(() => {
    const r = requestAnimationFrame(() => setShown(true))
    return () => cancelAnimationFrame(r)
  }, [])
  const remove = useGameStore(s => s.removeToast)
  return (
    <div className={'toast' + (cls ? ' ' + cls : '') + (shown ? ' show' : '')} onClick={() => remove(id)}>
      {text}
    </div>
  )
}
