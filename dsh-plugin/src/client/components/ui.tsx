// 共享 UI 原语，对应原 el/uiBtn/uiTable/kvGrid。沿用 game.css 类名。
import type { ReactNode } from 'react'

export function Btn({
  children, className, primary, danger, disabled, onClick, title,
}: {
  children: ReactNode
  className?: string
  primary?: boolean
  danger?: boolean
  disabled?: boolean
  onClick?: () => void
  title?: string
}) {
  const cls = 'uibtn' + (primary ? ' primary' : '') + (danger ? ' danger' : '') + (className ? ' ' + className : '')
  return (
    <button className={cls} disabled={disabled} onClick={onClick} title={title}>
      {children}
    </button>
  )
}

export function UiTable({ headers, rows }: { headers: string[]; rows: ReactNode[][] }) {
  return (
    <table className="ui">
      <tbody>
        <tr>
          {headers.map((h, i) => (
            <th key={i}>{h}</th>
          ))}
        </tr>
        {rows.map((r, ri) => (
          <tr key={ri}>
            {r.map((c, ci) => (
              <td key={ci}>{c}</td>
            ))}
          </tr>
        ))}
      </tbody>
    </table>
  )
}

export function kvGrid(obj: Record<string, unknown> | undefined | null, emptyHint?: string): ReactNode {
  const es = Object.entries(obj || {})
  if (!es.length) return <div className="muted">{emptyHint || '（无）'}</div>
  return (
    <div className="kv">
      {es.map(([k, v], i) => (
        <div key={i}>
          <b>{k}</b>
          {String(v)}
        </div>
      ))}
    </div>
  )
}
