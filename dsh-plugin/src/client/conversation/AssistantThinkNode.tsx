// dsh 渲染模式下，把 assistant 文本气泡改成「Think」折叠样式，
// 仿 ui-conversation 的 ReasoningRow：默认收起、灰色、可展开。
// 不依赖 harness 内部组件，自行内联，避免打包冲突。

interface AssistantBlockLike {
  kind?: string
  text?: string
}

function collectText(blocks: readonly AssistantBlockLike[] | undefined): string {
  if (!Array.isArray(blocks)) return ''
  const parts: string[] = []
  for (const block of blocks) {
    if (!block) continue
    if (block.kind === 'text' || block.kind === 'reasoning') {
      const text = typeof block.text === 'string' ? block.text : ''
      if (text) parts.push(text)
    }
  }
  return parts.join('\n').trim()
}

export function AssistantThinkNode({ node }: { node: any }) {
  const data = node?.data
  const text = collectText(data?.blocks)
  if (!text) return null
  const running = data?.status === 'running'
  const summary = running
    ? (text.split('\n').filter(Boolean).pop() || text)
    : (text.split('\n')[0] || text)
  return (
    <details style={{
      margin: '4px 0',
      padding: '4px 10px',
      borderLeft: '2px solid #4a3a27',
      borderRadius: 4,
      background: 'rgba(154,140,110,0.06)',
      color: '#9a8c6e',
      fontSize: 12,
      lineHeight: 1.55,
      userSelect: 'text',
    }}>
      <summary style={{
        cursor: 'pointer', color: '#7a6c52', fontWeight: 500,
        display: 'flex', alignItems: 'center', gap: 5,
        minWidth: 0, width: '100%',
        listStyle: 'none',
      }}>
        <span aria-hidden style={{ flex: '0 0 auto' }}>💭</span>
        <span style={{ flex: '0 0 auto' }}>Think{running ? '…' : ''}</span>
        <span style={{ marginLeft: 6, color: '#6f6354', fontWeight: 400, flex: '1 1 0', minWidth: 0, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
          {summary}
        </span>
      </summary>
      <div style={{ marginTop: 6, whiteSpace: 'pre-wrap', color: '#8a7c64' }}>{text}</div>
    </details>
  )
}
