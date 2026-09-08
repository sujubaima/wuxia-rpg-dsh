import type {
  BattleEntry, HpChange, ParsedAction, ParsedRow, StatusChange, TimedBattleEffect,
} from '../../types'

export type ResourceKind = 'hp' | 'mp'
export type FloatTone = 'damage' | 'critical' | 'heal' | 'mp-loss' | 'mp-gain' | 'miss' | 'buff' | 'expire'

export interface FighterDisplay {
  hp: string
  mp: string
  statuses: string[]
  cooldowns: string[]
  dead: boolean
  fled: boolean
}

export type ReplayCue =
  | { kind: 'lunge'; at: number; actor: string }
  | { kind: 'label'; at: number; actor: string; text: string; tone: 'attack' | 'item' | 'walk' }
  | { kind: 'projectile'; at: number; actor: string; target: string }
  | { kind: 'float'; at: number; target: string; text: string; tone: FloatTone }
  | { kind: 'resource'; at: number; target: string; resource: ResourceKind; value: number }
  | { kind: 'impact'; at: number; target: string; critical: boolean }
  | { kind: 'snapshot'; at: number; statuses: Record<string, string[]> }
  | { kind: 'defeat'; at: number; target: string }
  | { kind: 'flee'; at: number; target: string }

function splitValues(value: string | undefined, empty: string): string[] {
  if (!value || value === empty) return []
  return value.split('、').map(item => item.trim()).filter(Boolean)
}

function rowDisplay(row?: ParsedRow): FighterDisplay {
  return {
    hp: row?.气血 || '',
    mp: row?.内力 || '',
    statuses: splitValues(row?.状态, '无').filter(item => item !== '败阵' && item !== '逃走'),
    cooldowns: splitValues(row?.冷却, '无'),
    dead: Boolean(row?.败阵 || row?.状态列 === '败阵' || row?.状态 === '败阵'),
    fled: Boolean(row?.逃走 || row?.状态列 === '逃走' || row?.状态 === '逃走'),
  }
}

export function displayFromParse(parse: ParsedAction): Record<string, FighterDisplay> {
  const result: Record<string, FighterDisplay> = {}
  for (const [name, row] of Object.entries(parse.table)) result[name] = rowDisplay(row)
  return result
}

function resourceText(current: string, value: number): string {
  const slash = current.indexOf('/')
  return slash >= 0 ? `${value}${current.slice(slash)}` : String(value)
}

export function applyResource(
  state: Record<string, FighterDisplay>,
  name: string,
  resource: ResourceKind,
  value: number,
): Record<string, FighterDisplay> {
  if (!name || !Number.isFinite(value)) return state
  const current = state[name] || rowDisplay()
  return {
    ...state,
    [name]: {
      ...current,
      [resource]: resourceText(resource === 'hp' ? current.hp : current.mp, value),
    },
  }
}

export function applyStatusSnapshot(
  state: Record<string, FighterDisplay>,
  snapshot: Record<string, string[]>,
): Record<string, FighterDisplay> {
  let changed = false
  const next = { ...state }
  for (const [name, values] of Object.entries(snapshot || {})) {
    const current = next[name] || rowDisplay()
    const statuses = Array.isArray(values) ? values.map(String) : []
    next[name] = { ...current, statuses }
    changed = true
  }
  return changed ? next : state
}

export function applyMarker(
  state: Record<string, FighterDisplay>,
  name: string,
  marker: 'dead' | 'fled',
): Record<string, FighterDisplay> {
  if (!name) return state
  const current = state[name] || rowDisplay()
  return { ...state, [name]: { ...current, [marker]: true } }
}

function changes(value: HpChange | HpChange[] | undefined): HpChange[] {
  if (!value) return []
  return Array.isArray(value) ? value : [value]
}

function originalValue(value: HpChange | HpChange[] | undefined): number | null {
  for (const change of changes(value)) {
    if (Number.isFinite(Number(change?.原值))) return Number(change.原值)
  }
  return null
}

function seedResource(
  state: Record<string, FighterDisplay>,
  seen: Set<string>,
  name: string | undefined,
  resource: ResourceKind,
  value: HpChange | HpChange[] | undefined,
): Record<string, FighterDisplay> {
  if (!name) return state
  const key = `${name}|${resource}`
  if (seen.has(key)) return state
  const original = originalValue(value)
  if (original == null) return state
  seen.add(key)
  return applyResource(state, name, resource, original)
}

function seedTimed(
  state: Record<string, FighterDisplay>,
  seen: Set<string>,
  effects: TimedBattleEffect[] | undefined,
  resource: ResourceKind,
): Record<string, FighterDisplay> {
  let next = state
  for (const effect of effects || []) {
    if (!effect?.目标) continue
    next = seedResource(next, seen, effect.目标, resource, {
      原值: effect.原值,
      新值: effect.新值,
    })
  }
  return next
}

function badgeName(value: string): string {
  const bracket = /【([^】]+)】/.exec(value)
  return (bracket?.[1] || value).replace(/\([^)]*\)$/, '').trim()
}

function undoAppliedStatus(
  state: Record<string, FighterDisplay>,
  values: StatusChange[] | undefined,
  fallback: string,
): Record<string, FighterDisplay> {
  let next = state
  for (const status of values || []) {
    const target = status?.目标 || fallback
    const name = status?.名称 || ''
    const current = next[target]
    if (!target || !name || !current) continue
    const index = current.statuses.findIndex(value => badgeName(value) === badgeName(name))
    if (index < 0) continue
    const statuses = current.statuses.slice()
    statuses.splice(index, 1)
    next = { ...next, [target]: { ...current, statuses } }
  }
  return next
}

function seedStatusesBeforeFirst(
  state: Record<string, FighterDisplay>,
  entry: BattleEntry | undefined,
): Record<string, FighterDisplay> {
  if (!entry?.状态快照) return state
  let next = applyStatusSnapshot(state, entry.状态快照)
  const actor = entry.行动者 || ''
  if (entry.目标结算?.length) {
    for (const settle of entry.目标结算) {
      next = undoAppliedStatus(next, settle.施加状态, settle.目标 || '')
    }
    next = undoAppliedStatus(next, entry.施加状态, actor)
  } else {
    next = undoAppliedStatus(next, entry.施加状态, entry.目标 || actor)
  }
  for (const expired of entry.状态失效 || []) {
    const target = expired?.目标 || expired?.角色 || actor
    const name = expired?.名称 || ''
    if (!target || !name) continue
    const current = next[target] || rowDisplay()
    if (current.statuses.some(value => badgeName(value) === badgeName(name))) continue
    next = { ...next, [target]: { ...current, statuses: [...current.statuses, `【${name}】`] } }
  }
  return next
}

/** 用第一批回放条目的原值覆盖终态，避免首帧提前显示结算后数值和状态。 */
export function seedDisplayForReplay(
  parse: ParsedAction,
  entries: BattleEntry[],
): Record<string, FighterDisplay> {
  let state = seedStatusesBeforeFirst(displayFromParse(parse), entries[0])
  const seen = new Set<string>()
  const markerSeen = new Set<string>()
  for (const entry of entries) {
    const actor = entry.行动者
    const target = entry.目标
    state = seedResource(state, seen, actor, 'mp', entry.行动者内力变化)
    state = seedResource(state, seen, actor, 'hp', entry.行动者气血变化)
    state = seedResource(state, seen, actor, 'hp', entry.气血变化)
    state = seedResource(state, seen, actor, 'mp', entry.内力变化)
    state = seedResource(state, seen, target, 'hp', entry.目标气血变化)
    state = seedResource(state, seen, target, 'mp', entry.目标内力变化)
    for (const settle of entry.目标结算 || []) {
      state = seedResource(state, seen, settle.目标, 'hp', settle.目标气血变化)
      state = seedResource(state, seen, settle.目标, 'mp', settle.目标内力变化)
      if (settle.击败 && settle.目标 && !markerSeen.has(`${settle.目标}|dead`)) {
        const current = state[settle.目标] || rowDisplay()
        state = { ...state, [settle.目标]: { ...current, dead: false } }
        markerSeen.add(`${settle.目标}|dead`)
      }
    }
    state = seedTimed(state, seen, entry.持续伤害, 'hp')
    state = seedTimed(state, seen, entry.持续恢复, 'hp')
    state = seedTimed(state, seen, entry.持续恢复内力, 'mp')
    if (entry.击败 && target && !markerSeen.has(`${target}|dead`)) {
      const current = state[target] || rowDisplay()
      state = { ...state, [target]: { ...current, dead: false } }
      markerSeen.add(`${target}|dead`)
    }
    if (entry.类型 === '逃跑' && entry.逃跑成功 && actor && !markerSeen.has(`${actor}|fled`)) {
      const current = state[actor] || rowDisplay()
      state = { ...state, [actor]: { ...current, fled: false } }
      markerSeen.add(`${actor}|fled`)
    }
  }
  return state
}

function actionText(entry: BattleEntry): string {
  if (entry.类型 === '武学') return `【${entry.技能 || '武学'}${entry.招式 ? `·${entry.招式}` : ''}】${entry.目标 ? ` → ${entry.目标}` : ''}`
  if (entry.类型 === '物品') return `用药【${entry.物品 || '物品'}】${entry.目标 ? ` → ${entry.目标}` : ''}`
  if (entry.类型 === '休息') return '敛气调息'
  if (entry.类型 === '逃跑') return '要遁走！'
  if (entry.类型 === '认输') return '认输'
  if (entry.类型 === '运功') return '运功凝神'
  if (entry.类型 === '无法行动') return String(entry.原因 || '无法行动')
  return '行动'
}

function labelTone(entry: BattleEntry): 'attack' | 'item' | 'walk' {
  if (entry.类型 === '物品') return 'item'
  if (['休息', '逃跑', '认输', '运功', '无法行动'].includes(String(entry.类型))) return 'walk'
  return 'attack'
}

function pushResourceCues(
  cues: ReplayCue[],
  target: string | undefined,
  resource: ResourceKind,
  value: HpChange | HpChange[] | undefined,
  at: number,
  critical = false,
): void {
  if (!target) return
  let offset = 0
  for (const change of changes(value)) {
    const before = Number(change?.原值)
    const after = Number(change?.新值)
    if (!Number.isFinite(after)) continue
    const time = at + offset
    cues.push({ kind: 'resource', at: time, target, resource, value: after })
    if (Number.isFinite(before) && before !== after) {
      const delta = after - before
      const tone: FloatTone = resource === 'mp'
        ? delta > 0 ? 'mp-gain' : 'mp-loss'
        : delta > 0 ? 'heal' : critical ? 'critical' : 'damage'
      cues.push({ kind: 'float', at: time, target, text: `${delta > 0 ? '+' : ''}${delta}`, tone })
    }
    offset += 50
  }
}

function pushStatusCues(
  cues: ReplayCue[],
  values: StatusChange[] | undefined,
  fallback: string,
  at: number,
): void {
  for (const [index, status] of (values || []).entries()) {
    const target = status?.目标 || fallback
    if (!target || !status?.名称) continue
    cues.push({ kind: 'float', at: at + index * 70, target, text: `＋${status.名称}`, tone: 'buff' })
  }
}

function pushExpiredCues(cues: ReplayCue[], entry: BattleEntry, at: number): void {
  for (const [index, status] of (entry.状态失效 || []).entries()) {
    const target = status?.目标 || status?.角色 || entry.行动者 || ''
    if (!target || !status?.名称) continue
    cues.push({ kind: 'float', at: at + index * 70, target, text: `－${status.名称}`, tone: 'expire' })
  }
}

function pushTimedCues(
  cues: ReplayCue[],
  effects: TimedBattleEffect[] | undefined,
  resource: ResourceKind,
  at: number,
): void {
  for (const [index, effect] of (effects || []).entries()) {
    if (!effect?.目标 || !Number.isFinite(Number(effect.新值))) continue
    const time = at + index * 80
    const before = Number(effect.原值)
    const after = Number(effect.新值)
    cues.push({ kind: 'resource', at: time, target: effect.目标, resource, value: after })
    const delta = Number.isFinite(before) ? after - before : Number(effect.数值 || 0)
    if (delta) {
      const tone: FloatTone = resource === 'mp'
        ? delta > 0 ? 'mp-gain' : 'mp-loss'
        : delta > 0 ? 'heal' : 'damage'
      const source = effect.来源 ? `${effect.来源} ` : ''
      cues.push({ kind: 'float', at: time, target: effect.目标, text: `${source}${delta > 0 ? '+' : ''}${delta}`, tone })
    }
  }
}

/** 将一条 engine 回合详情展开为可测试、可缩放的 Card 内动画 cue。 */
export function buildReplayCues(entry: BattleEntry): ReplayCue[] {
  const cues: ReplayCue[] = []
  const actor = entry.行动者 || ''
  if (actor) {
    cues.push({ kind: 'label', at: 0, actor, text: actionText(entry), tone: labelTone(entry) })
    if (entry.类型 !== '无法行动') cues.push({ kind: 'lunge', at: 0, actor })
  }

  pushResourceCues(cues, actor, 'mp', entry.行动者内力变化, 90)
  pushResourceCues(cues, actor, 'hp', entry.行动者气血变化, 90)

  if (entry.类型 === '武学') {
    const targets = entry.目标结算?.length
      ? entry.目标结算
      : entry.目标 ? [{
          目标: entry.目标,
          闪避: entry.闪避,
          暴击: entry.暴击,
          击败: entry.击败,
          目标气血变化: entry.目标气血变化,
          目标内力变化: entry.目标内力变化,
          施加状态: entry.施加状态,
        }] : []
    targets.forEach((target, index) => {
      const name = target.目标 || ''
      if (!name) return
      const projectileAt = 300 + index * 100
      const impactAt = 760 + index * 110
      cues.push({ kind: 'projectile', at: projectileAt, actor, target: name })
      if (target.闪避) {
        cues.push({ kind: 'float', at: impactAt, target: name, text: '闪避', tone: 'miss' })
        return
      }
      cues.push({ kind: 'impact', at: impactAt, target: name, critical: Boolean(target.暴击) })
      pushResourceCues(cues, name, 'hp', target.目标气血变化, impactAt, Boolean(target.暴击))
      pushResourceCues(cues, name, 'mp', target.目标内力变化, impactAt)
      pushStatusCues(cues, target.施加状态, name, impactAt + 90)
      if (target.击败) cues.push({ kind: 'defeat', at: impactAt + 130, target: name })
    })
    if (entry.目标结算?.length) pushStatusCues(cues, entry.施加状态, actor, 900)
  } else if (entry.类型 === '物品') {
    const target = entry.目标 || actor
    pushResourceCues(cues, target, 'hp', entry.目标气血变化 || entry.气血变化, 430)
    pushResourceCues(cues, target, 'mp', entry.目标内力变化 || entry.内力变化, 430)
    pushStatusCues(cues, entry.施加状态, target, 520)
  } else if (entry.类型 === '休息') {
    pushResourceCues(cues, actor, 'hp', entry.气血变化, 350)
    pushResourceCues(cues, actor, 'mp', entry.内力变化, 350)
  } else if (entry.类型 === '逃跑') {
    if (entry.逃跑成功) cues.push({ kind: 'flee', at: 520, target: actor })
    else cues.push({ kind: 'float', at: 520, target: actor, text: '未脱身', tone: 'miss' })
  } else if (entry.类型 === '运功') {
    for (const [index, status] of (entry.获得状态 || []).entries()) {
      cues.push({ kind: 'float', at: 380 + index * 70, target: actor, text: `运功·${status}`, tone: 'buff' })
    }
  }

  if (entry.类型 !== '武学' && entry.类型 !== '物品') {
    pushStatusCues(cues, entry.施加状态, actor, 870)
  }
  pushExpiredCues(cues, entry, 980)
  pushTimedCues(cues, entry.持续伤害, 'hp', 1050)
  pushTimedCues(cues, entry.持续恢复, 'hp', 1050)
  pushTimedCues(cues, entry.持续恢复内力, 'mp', 1120)
  if (entry.状态快照) cues.push({ kind: 'snapshot', at: 1280, statuses: entry.状态快照 })

  return cues.sort((left, right) => left.at - right.at)
}

export function replayStepDuration(queueLength: number): number {
  if (queueLength > 12) return 1050
  if (queueLength > 5) return 1450
  return 1900
}
