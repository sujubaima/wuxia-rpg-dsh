import type { CSSProperties, ReactNode } from 'react'
import type { PanelRequest, PanelResponse } from '../panel-api'

const border = '#3a2f22'
const muted = '#9a8c6e'

export interface PanelProps {
  slot: number
  members: string[]
  request: PanelRequest
}

export const sectionStyle: CSSProperties = {
  margin: '14px 0 7px', color: '#c8a456', fontSize: 13, letterSpacing: 1,
}

export const selectStyle: CSSProperties = {
  padding: '5px 8px', color: '#e8dcc4', background: '#17130f', border: `1px solid ${border}`,
  borderRadius: 5, fontSize: 12,
}

export function PanelDescription({ children }: { children: ReactNode }) {
  if (!children) return null
  return <div style={{ marginBottom: 10, color: muted, fontSize: 12, lineHeight: 1.55 }}>{children}</div>
}

export function PanelButton({
  children, onClick, disabled, active, danger, title,
}: {
  children: ReactNode
  onClick?: () => void
  disabled?: boolean
  active?: boolean
  danger?: boolean
  title?: string
}) {
  const color = danger ? '#d77b6f' : active ? '#f0cf82' : '#c8a456'
  return (
    <button
      type="button"
      title={title}
      disabled={disabled}
      onClick={onClick}
      style={{
        padding: '4px 9px', margin: '1px 2px 1px 0', color,
        background: active ? '#352815' : 'transparent', border: `1px solid ${active ? '#a47d35' : '#6f5527'}`,
        borderRadius: 5, fontSize: 12, cursor: disabled ? 'default' : 'pointer',
        opacity: disabled ? 0.45 : 1, whiteSpace: 'nowrap',
      }}
    >
      {children}
    </button>
  )
}

export function PanelNotice({ kind, children }: { kind: 'error' | 'notice'; children?: ReactNode }) {
  if (!children) return null
  return (
    <div style={{
      margin: '8px 0', padding: '7px 9px', borderRadius: 6, fontSize: 12, lineHeight: 1.5,
      color: kind === 'error' ? '#ed998d' : '#a9c98a',
      background: kind === 'error' ? '#2b1715' : '#172316',
      border: `1px solid ${kind === 'error' ? '#68352e' : '#405d35'}`,
      whiteSpace: 'pre-wrap',
    }}>
      {children}
    </div>
  )
}

export function LoadingState({ text = '读取中…' }: { text?: string }) {
  return <div style={{ padding: '22px 4px', color: muted, textAlign: 'center', fontSize: 12 }}>{text}</div>
}

export function EmptyState({ children = '（无）' }: { children?: ReactNode }) {
  return <div style={{ padding: '8px 10px', color: muted, background: '#17130f', borderRadius: 6, fontSize: 12 }}>{children}</div>
}

export function SectionTitle({ children }: { children: ReactNode }) {
  return <h4 style={sectionStyle}>{children}</h4>
}

export function PanelTable({ headers, rows }: { headers: ReactNode[]; rows: ReactNode[][] }) {
  if (!rows.length) return <EmptyState />
  return (
    <div style={{ width: '100%', overflowX: 'auto', border: `1px solid ${border}`, borderRadius: 6 }}>
      <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 12, minWidth: 'max-content' }}>
        <thead>
          <tr>
            {headers.map((header, index) => (
              <th key={index} style={{ padding: '6px 8px', color: muted, background: '#17130f', borderBottom: `1px solid ${border}`, textAlign: 'left', fontWeight: 500, whiteSpace: 'nowrap' }}>
                {header}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {rows.map((row, rowIndex) => (
            <tr key={rowIndex}>
              {row.map((cell, cellIndex) => (
                <td key={cellIndex} style={{ padding: '6px 8px', color: '#ddd0b8', borderBottom: rowIndex === rows.length - 1 ? 'none' : `1px solid ${border}`, verticalAlign: 'top', lineHeight: 1.45 }}>
                  {cell}
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}

export function KeyValueGrid({ data, empty = '（无）' }: { data?: Record<string, unknown> | null; empty?: string }) {
  const entries = Object.entries(data || {})
  if (!entries.length) return <EmptyState>{empty}</EmptyState>
  return (
    <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(130px, 1fr))', gap: 5 }}>
      {entries.map(([key, value]) => (
        <div key={key} style={{ padding: '6px 8px', background: '#17130f', border: `1px solid ${border}`, borderRadius: 5, minWidth: 0 }}>
          <div style={{ color: muted, fontSize: 11, marginBottom: 2 }}>{key}</div>
          <div style={{ color: '#e8dcc4', overflowWrap: 'anywhere' }}>{displayValue(value)}</div>
        </div>
      ))}
    </div>
  )
}

export function displayValue(value: unknown): string {
  if (value == null || value === '') return '—'
  if (Array.isArray(value)) return value.map(displayValue).join('、') || '—'
  if (typeof value === 'object') return JSON.stringify(value)
  return String(value)
}

export function formatSaveTimestamp(value: unknown): string {
  const raw = String(value || '')
  const matched = /^(\d{4})(\d{2})(\d{2})_(\d{2})(\d{2})(\d{2})(?:_(\d+))?$/.exec(raw)
  if (!matched) return raw || '—'
  const suffix = matched[7] ? ` (${matched[7]})` : ''
  return `${matched[1]}/${matched[2]}/${matched[3]} ${matched[4]}:${matched[5]}:${matched[6]}${suffix}`
}

export function engineError(data: any): string | null {
  if (!data) return 'engine 未返回结果'
  if (data.错误 != null) return String(data.错误)
  const failed = Array.isArray(data.结算) ? data.结算.find((entry: any) => entry?.ok === false) : null
  if (failed) return String(failed.msg || failed.变更 || 'engine 操作失败')
  return null
}

export function resultNotice(data: any): string {
  const parts: string[] = []
  if (data?.提示) parts.push(String(data.提示))
  for (const entry of Array.isArray(data?.结算) ? data.结算 : []) {
    if (entry?.msg) parts.push(String(entry.msg))
    else if (entry?.变更) parts.push(String(entry.变更))
  }
  return parts.join('\n')
}

export async function oneResult(
  request: PanelRequest,
  slot: number,
  action: Record<string, unknown>,
): Promise<{ data: any; response: PanelResponse }> {
  const response = await request(slot, [action])
  const data = response.results[0]
  const error = engineError(data)
  if (error) throw new Error(error)
  return { data, response }
}
