import type { CSSProperties } from 'react'
import { Fragment } from 'react'
import { jsx } from 'react/jsx-runtime'

export const CARD_STYLE: CSSProperties = {
  padding: '14px 18px', margin: '8px 0 4px', borderRadius: 10,
  border: '2px solid #8a6a2a', background: '#221c16',
  boxShadow: '0 0 0 1px rgba(200,164,86,0.14), 0 4px 16px rgba(0,0,0,0.38)',
  color: '#e8dcc4', fontSize: 13.5, lineHeight: 1.75,
}

export const TITLE_COLOR = '#c8a456'
export const DIM_COLOR = '#9a8c6e'
export const BORDER_COLOR = '#3a2f22'

export function formatPosition(value: unknown): string {
  return String(value || '').replace('·', ' · ')
}

function renderInlineHighlights(text: string) {
  return text.split(/(`[^`\n]+`)/g).map((part, index) => {
    if (!part.startsWith('`') || !part.endsWith('`')) {
      return jsx(Fragment, { children: part }, index)
    }
    return jsx('code', {
      style: {
        padding: '1px 5px', borderRadius: 3, background: '#0c0a07',
        color: TITLE_COLOR, fontFamily: '"SFMono-Regular", Consolas, monospace',
        fontSize: '0.92em',
      },
      children: part.slice(1, -1),
    }, index)
  })
}

/** 游历/战前 Card 共用的抬头、剧情与状态变化。 */
export function ExplorationSummary({ data }: { data: any }) {
  const position = formatPosition(data?.当前位置)
  const heading = `【${position}】 ${data?.时段 || ''} ${data?.时间 || ''}`.trim()
  const narration = String(data?.剧情描写 || '').replace(/\\n/g, '\n')
  const changes = ((data?.结算 as any[]) || [])
    .map((result: any) => result && result.变更)
    .filter(Boolean) as string[]

  return jsx(Fragment, {
    children: [
      heading ? jsx('div', {
        style: { fontWeight: 600, color: TITLE_COLOR, marginBottom: 8, letterSpacing: 1 },
        children: heading,
      }, 'heading') : null,
      narration ? jsx('div', {
        style: { marginBottom: 10, whiteSpace: 'pre-wrap' },
        children: renderInlineHighlights(
          narration.split(/\n{2,}/).map(text => text.trim()).filter(Boolean).join('\n\n'),
        ),
      }, 'narration') : null,
      changes.length > 0 ? jsx('div', {
        style: { display: 'flex', flexWrap: 'wrap', gap: 6, marginBottom: 10 },
        children: changes.map((change, index) => {
          const negative = /体力-|气血-|内力-/.test(change)
          return jsx('span', {
            style: {
              padding: '1px 8px', borderRadius: 4, fontSize: 12,
              background: negative ? 'rgba(196,90,74,0.14)' : 'rgba(200,164,86,0.12)',
              color: negative ? '#c45a4a' : TITLE_COLOR,
              border: `1px solid ${negative ? 'rgba(196,90,74,0.4)' : 'rgba(138,106,42,0.4)'}`,
            },
            children: change,
          }, index)
        }),
      }, 'changes') : null,
    ],
  })
}
