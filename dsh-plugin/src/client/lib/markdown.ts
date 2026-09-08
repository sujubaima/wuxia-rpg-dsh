// Markdown 渲染，移植自 game-chat.js 的 esc/renderInline/render。
// 输出 HTML 串，调用方用 dangerouslySetInnerHTML 注入（内容为受信本地 GM 文本）。

export function esc(s: unknown): string {
  return String(s).replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
}

export function renderInline(s: string): string {
  s = esc(s)
  s = s.replace(/`([^`]+)`/g, '<code>$1</code>')
  s = s.replace(/\*\*([^*]+)\*\*/g, '<strong>$1</strong>')
  s = s.replace(/(?<!\*)\*([^*\n]+)\*(?!\*)/g, '<em>$1</em>')
  s = s.replace(/\[([^\]]+)\]\(([^)\s]+)\)/g, '<a href="$2" target="_blank" rel="noopener">$1</a>')
  return s
}

export function render(text: string): string {
  if (!text) return ''
  const lines = text.replace(/\r\n/g, '\n').split('\n')
  const out: string[] = []
  let i = 0
  let para: string[] = []
  const flushPara = () => {
    if (para.length) {
      out.push('<p>' + para.map(renderInline).join('<br>') + '</p>')
      para = []
    }
  }
  while (i < lines.length) {
    const ln = lines[i]
    const fence = ln.match(/^```(\w*)/)
    if (fence) {
      flushPara()
      const lang = fence[1] || ''
      const code: string[] = []
      i++
      while (i < lines.length && !lines[i].startsWith('```')) {
        code.push(lines[i])
        i++
      }
      i++
      out.push('<pre><code class="lang-' + esc(lang) + '">' + esc(code.join('\n')) + '</code></pre>')
      continue
    }
    if (/^\s*([-*_])\1{2,}\s*$/.test(ln)) {
      flushPara()
      out.push('<hr>')
      i++
      continue
    }
    const h = ln.match(/^(#{1,6})\s+(.*)$/)
    if (h) {
      flushPara()
      const l = h[1].length
      out.push('<h' + l + '>' + renderInline(h[2]) + '</h' + l + '>')
      i++
      continue
    }
    if (/^>\s?/.test(ln)) {
      flushPara()
      const q: string[] = []
      while (i < lines.length && /^>\s?/.test(lines[i])) {
        q.push(lines[i].replace(/^>\s?/, ''))
        i++
      }
      out.push('<blockquote>' + renderInline(q.join('\n').replace(/\n/g, '<br>')) + '</blockquote>')
      continue
    }
    if (/^\s*[-*+]\s+/.test(ln)) {
      flushPara()
      const items: string[] = []
      while (i < lines.length && /^\s*[-*+]\s+/.test(lines[i])) {
        items.push('<li>' + renderInline(lines[i].replace(/^\s*[-*+]\s+/, '')) + '</li>')
        i++
      }
      out.push('<ul>' + items.join('') + '</ul>')
      continue
    }
    if (/^\s*\d+\.\s+/.test(ln)) {
      flushPara()
      const items: string[] = []
      while (i < lines.length && /^\s*\d+\.\s+/.test(lines[i])) {
        items.push('<li>' + renderInline(lines[i].replace(/^\s*\d+\.\s+/, '')) + '</li>')
        i++
      }
      out.push('<ol>' + items.join('') + '</ol>')
      continue
    }
    if (i + 1 < lines.length && /\|/.test(ln) && /^\s*\|?[\s:|-]+\|?\s*$/.test(lines[i + 1])) {
      flushPara()
      const rows: string[] = []
      const header = ln.split('|').map(c => c.trim()).slice(ln.startsWith('|') ? 1 : 0, ln.endsWith('|') ? -1 : undefined)
      i += 2
      rows.push('<tr>' + header.map(c2 => '<th>' + renderInline(c2) + '</th>').join('') + '</tr>')
      while (i < lines.length && /\|/.test(lines[i])) {
        const cells = lines[i].split('|').slice(ln.startsWith('|') ? 1 : 0, ln.endsWith('|') ? -1 : undefined).map(c2 => c2.trim())
        rows.push('<tr>' + cells.map(c2 => '<td>' + renderInline(c2) + '</td>').join('') + '</tr>')
        i++
      }
      out.push('<table>' + rows.join('') + '</table>')
      continue
    }
    if (!ln.trim()) {
      flushPara()
      i++
      continue
    }
    para.push(ln)
    i++
  }
  flushPara()
  return out.join('')
}
