// 场景图布局与 SVG 渲染，移植自 game-tabs.js layoutSceneGraph/renderSceneSvg。
import { esc } from './markdown'

const DIR_VEC: Record<string, [number, number]> = {
  北: [0, -1], 东北: [1, -1], 东: [1, 0], 东南: [1, 1],
  南: [0, 1], 西南: [-1, 1], 西: [-1, 0], 西北: [-1, -1],
}

interface LayoutResult {
  pos: Map<string, [number, number]>
  edges: [string, string][]
}

function layoutSceneGraph(adj: Record<string, Record<string, string>>, cur: string): LayoutResult {
  const pos = new Map<string, [number, number]>()
  const edges: [string, string][] = []
  if (cur == null || !(cur in adj)) cur = Object.keys(adj)[0]
  if (!cur) return { pos, edges }
  const occ = new Set<string>()
  const key = (x: number, y: number) => x + ',' + y
  const parent: Record<string, string | null> = {}
  pos.set(cur, [0, 0])
  occ.add(key(0, 0))
  const q: string[] = [cur]
  parent[cur] = null
  while (q.length) {
    const a = q.shift()!
    const [ax, ay] = pos.get(a)!
    for (const dir of Object.keys(DIR_VEC)) {
      const b = (adj[a] || {})[dir]
      if (!b) continue
      if (!pos.has(b)) {
        const v = DIR_VEC[dir]
        let x = ax + v[0], y = ay + v[1], step = 0
        while (occ.has(key(x, y)) && step < 40) { x += v[0]; y += v[1]; step++ }
        if (step >= 40) continue
        pos.set(b, [x, y])
        occ.add(key(x, y))
        parent[b] = a
        q.push(b)
        edges.push([a, b])
      } else if (parent[b] === a) {
        edges.push([a, b])
      }
    }
  }
  let farX = 0
  pos.forEach(([x]) => { if (x >= farX) farX = x + 2 })
  for (const n in adj) if (!pos.has(n)) { pos.set(n, [farX, 0]); farX += 2 }
  return { pos, edges }
}

export function renderSceneSvg(adj: Record<string, Record<string, string>>, cur: string, stationExit?: string): string {
  const { pos, edges } = layoutSceneGraph(adj, cur)
  if (!pos.size) return ''
  const GW = 170, GH = 100, NW = 130, NH = 44
  let minX = 0, minY = 0, maxX = 0, maxY = 0
  pos.forEach(([x, y]) => { minX = Math.min(minX, x); maxX = Math.max(maxX, x); minY = Math.min(minY, y); maxY = Math.max(maxY, y) })
  const W = (maxX - minX + 1) * GW, H = (maxY - minY + 1) * GH
  const cx = (x: number) => (x - minX) * GW + GW / 2
  const cy = (y: number) => (y - minY) * GH + GH / 2
  const parts: string[] = []
  parts.push(`<svg viewBox="0 0 ${W} ${H}" width="${W}" height="${H}" style="display:block">`)
  for (const [a, b] of edges) {
    const [ax, ay] = pos.get(a)!, [bx, by] = pos.get(b)!
    const dash = a === stationExit || b === stationExit ? ' stroke-dasharray="4 4"' : ''
    parts.push(`<line x1="${cx(ax)}" y1="${cy(ay)}" x2="${cx(bx)}" y2="${cy(by)}" stroke="#4a3f2a" stroke-width="1.5"${dash}/>`)
  }
  pos.forEach(([x, y], name) => {
    const isCur = name === cur, isExit = name === stationExit
    const fill = isCur ? '#2e2310' : '#221c16'
    const stroke = isExit ? '#d0a75a' : isCur ? '#c8a456' : '#4a3f2a'
    const sw = isCur ? 2 : 1
    const sd = isExit ? ' stroke-dasharray="5 3"' : ''
    parts.push(`<g><rect x="${cx(x) - NW / 2}" y="${cy(y) - NH / 2}" width="${NW}" height="${NH}" rx="8" fill="${fill}" stroke="${stroke}" stroke-width="${sw}"${sd}/>`)
    parts.push(`<text x="${cx(x)}" y="${cy(y) + Math.min(4, NH / 2 - 10)}" text-anchor="middle" font-size="12.5" fill="${isCur ? '#e8d8a8' : '#b8a888'}">${esc((isCur ? '◈ ' : '') + name + (isExit ? ' ⛟' : ''))}</text></g>`)
  })
  parts.push('</svg>')
  return parts.join('')
}
