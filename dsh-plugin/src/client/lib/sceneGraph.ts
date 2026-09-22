// 场景图布局与 SVG 渲染，移植自 game-tabs.js layoutSceneGraph/renderSceneSvg。
import { esc } from './markdown'

const GW = 170, GH = 100, NW = 130, NH = 44

const DIR_VEC: Record<string, [number, number]> = {
  北: [0, -1], 东北: [1, -1], 东: [1, 0], 东南: [1, 1],
  南: [0, 1], 西南: [-1, 1], 西: [-1, 0], 西北: [-1, -1],
}

interface LayoutResult {
  pos: Map<string, [number, number]>
  edges: [string, string][]
}

function layoutSceneGraph(adj: Record<string, Record<string, string>>, root: string): LayoutResult {
  const pos = new Map<string, [number, number]>()
  const edges: [string, string][] = []
  if (root == null || !(root in adj)) root = Object.keys(adj)[0]
  if (!root) return { pos, edges }
  const occ = new Set<string>()
  const key = (x: number, y: number) => x + ',' + y
  const parent: Record<string, string | null> = {}
  pos.set(root, [0, 0])
  occ.add(key(0, 0))
  const q: string[] = [root]
  parent[root] = null
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

// 线段是否穿过某节点盒子（Liang-Barsky 裁剪，交于 [0,1] 区间即有交）
function segCrossBox(x1: number, y1: number, x2: number, y2: number, bx: number, by: number): boolean {
  const xmin = bx - NW / 2, xmax = bx + NW / 2, ymin = by - NH / 2, ymax = by + NH / 2
  const dx = x2 - x1, dy = y2 - y1
  let t0 = 0, t1 = 1
  const clip = (p: number, q: number): boolean => {
    if (p === 0) return q >= 0
    const r = q / p
    if (p < 0) { if (r > t1) return false; if (r > t0) t0 = r }
    else { if (r < t0) return false; if (r < t1) t1 = r }
    return true
  }
  return clip(-dx, x1 - xmin) && clip(dx, xmax - x1) && clip(-dy, y1 - ymin) && clip(dy, ymax - y1)
}

// 生成边的 path：直连会穿过其他节点盒子时，改为向外弓的二次贝塞尔绕行，
// 避免"连线穿盒"被误读成相邻场景直通（如杭州 断桥→孤山 直线正好穿过海港）。
// 弓出幅度从穿盒障碍的最小需求起按几何级数逐档放大，采样曲线验证不撞任何盒；
// 两侧都失败时取需求较小的一侧按上限内最大幅度尽力绕
function edgePathD(x1: number, y1: number, x2: number, y2: number, obstacles: [number, number][]): string {
  const L = Math.hypot(x2 - x1, y2 - y1)
  if (L === 0) return `M ${x1} ${y1} L ${x2} ${y2}`
  const ux = (x2 - x1) / L, uy = (y2 - y1) / L // 沿边单位向量
  const px = -uy, py = ux // 垂直于边
  let reqPos = 0, reqNeg = 0 // 两侧各自需要的最小弓出幅度
  for (const [ox, oy] of obstacles) {
    if (!segCrossBox(x1, y1, x2, y2, ox, oy)) continue
    const t = Math.min(0.9, Math.max(0.1, ((ox - x1) * ux + (oy - y1) * uy) / L))
    const h = (ox - x1) * px + (oy - y1) * py // 盒心相对弦线的带符号垂距
    const support = (NW / 2) * Math.abs(px) + (NH / 2) * Math.abs(py) // 盒子垂直于边方向的半宽
    const f = Math.max(0.5, 4 * t * (1 - t)) // 贝塞尔在障碍处的偏移系数（弦中点为 1）
    reqPos = Math.max(reqPos, (support + 10 + h) / f)
    reqNeg = Math.max(reqNeg, (support + 10 - h) / f)
  }
  if (!reqPos && !reqNeg) return `M ${x1} ${y1} L ${x2} ${y2}`
  const CAP = 240, STEPS = 28
  const clean = (dev: number, s: number): boolean => {
    const mx = (x1 + x2) / 2 + px * s * dev * 2, my = (y1 + y2) / 2 + py * s * dev * 2
    const n = Math.max(24, Math.round(L / 6))
    for (let i = 0; i <= n; i++) {
      const t = i / n, u = 1 - t
      const bx = u * u * x1 + 2 * t * u * mx + t * t * x2
      const by = u * u * y1 + 2 * t * u * my + t * t * y2
      for (const [ox, oy] of obstacles)
        if (Math.abs(bx - ox) < NW / 2 + 2 && Math.abs(by - oy) < NH / 2 + 2) return false
    }
    return true
  }
  let bestDev = 0, bestS = 0
  for (const s of [1, -1]) {
    const dev0 = s > 0 ? reqPos : reqNeg
    if (dev0 > CAP) continue
    const ratio = Math.pow(CAP / dev0, 1 / (STEPS - 1))
    for (let i = 0; i < STEPS; i++) {
      const dev = dev0 * Math.pow(ratio, i)
      if (clean(dev, s)) { if (!bestS || dev < bestDev) { bestDev = dev; bestS = s } break }
    }
  }
  if (!bestS) {
    bestS = reqPos <= reqNeg ? 1 : -1
    bestDev = Math.min(bestS > 0 ? reqPos : reqNeg, CAP)
  }
  const mx = (x1 + x2) / 2 + px * bestS * bestDev * 2
  const my = (y1 + y2) / 2 + py * bestS * bestDev * 2
  return `M ${x1} ${y1} Q ${mx} ${my} ${x2} ${y2}`
}

export function renderSceneSvg(adj: Record<string, Record<string, string>>, cur: string, stationExit?: string): string {
  // 布局根取固定锚点（驿站出口），玩家移动不重排整图，仅高亮变化；地图增删场景才改变形状
  const root = stationExit && stationExit in adj ? stationExit : Object.keys(adj)[0]
  const { pos, edges } = layoutSceneGraph(adj, root)
  if (!pos.size) return ''
  let minX = 0, minY = 0, maxX = 0, maxY = 0
  pos.forEach(([x, y]) => { minX = Math.min(minX, x); maxX = Math.max(maxX, x); minY = Math.min(minY, y); maxY = Math.max(maxY, y) })
  const W = (maxX - minX + 1) * GW, H = (maxY - minY + 1) * GH
  const cx = (x: number) => (x - minX) * GW + GW / 2
  const cy = (y: number) => (y - minY) * GH + GH / 2
  const centers = new Map<string, [number, number]>()
  pos.forEach(([x, y], name) => centers.set(name, [cx(x), cy(y)]))
  const parts: string[] = []
  parts.push(`<svg viewBox="0 0 ${W} ${H}" width="${W}" height="${H}" style="display:block">`)
  for (const [a, b] of edges) {
    const [ax, ay] = centers.get(a)!, [bx, by] = centers.get(b)!
    const obstacles: [number, number][] = []
    centers.forEach(([ox, oy], name) => { if (name !== a && name !== b) obstacles.push([ox, oy]) })
    parts.push(`<path d="${edgePathD(ax, ay, bx, by, obstacles)}" fill="none" stroke="#4a3f2a" stroke-width="1.5"/>`)
  }
  pos.forEach(([x, y], name) => {
    const isCur = name === cur, isExit = name === stationExit
    const fill = isCur ? '#2e2310' : '#221c16'
    const stroke = isCur ? '#c8a456' : '#4a3f2a'
    const sw = isCur ? 2 : 1
    parts.push(`<g><rect x="${cx(x) - NW / 2}" y="${cy(y) - NH / 2}" width="${NW}" height="${NH}" rx="8" fill="${fill}" stroke="${stroke}" stroke-width="${sw}"/>`)
    parts.push(`<text x="${cx(x)}" y="${cy(y) + Math.min(4, NH / 2 - 10)}" text-anchor="middle" font-size="12.5" fill="${isCur ? '#e8d8a8' : '#b8a888'}">${esc((isCur ? '◈ ' : '') + name + (isExit ? ' ⛟' : ''))}</text></g>`)
  })
  parts.push('</svg>')
  return parts.join('')
}
