import { useMemo, useRef, useState } from 'react'
import { parseActionInfo, parsePlayerUI, rosterParse } from '../../lib/battleParse'
import type {
  BattleEntry, ParsedAction, ParsedItem, ParsedRow, ParsedSkill,
} from '../../types'
import type { BattleRequest } from '../battle-api'
import { useBattleMode } from '../battle-mode'
import { useParty } from '../party-store'
import { engineError, PanelNotice } from '../panels/PanelPrimitives'
import { CARD_STYLE, BORDER_COLOR, DIM_COLOR, TITLE_COLOR } from '../ExplorationSummary'
import type { FighterDisplay } from './replay'
import { useCardBattleReplay } from './useCardBattleReplay'

const ALLY_COLOR = '#9aa8c8'
const ENEMY_COLOR = '#d99a7a'
const OK_COLOR = '#8db36a'
const DANGER_COLOR = '#d77b6f'
const FIGHTER_CARD_WIDTH = 158
const FIGHTER_CARD_HEIGHT = 116

type Side = 'ally' | 'enemy'
type TargetPick = {
  kind: 'skill' | 'item'
  name: string
  side: Side
  noSelf: boolean
}

function battleParse(data: any): ParsedAction {
  if (data?.行动信息 && typeof data.行动信息 === 'object') {
    return parseActionInfo(data.行动信息)
  }
  return parsePlayerUI(typeof data?.玩家界面 === 'string' ? data.玩家界面 : '')
}

function barValues(value?: string): { current: number; maximum: number; percent: number } | null {
  if (!value || !value.includes('/')) return null
  const [currentRaw, maximumRaw] = value.split('/')
  const current = Number(currentRaw)
  const maximum = Number(maximumRaw)
  if (!Number.isFinite(current) || !Number.isFinite(maximum) || maximum <= 0) return null
  return { current, maximum, percent: Math.max(0, Math.min(100, current / maximum * 100)) }
}

function statusTags(row?: ParsedRow): string[] {
  if (!row?.状态 || row.状态 === '无' || row.状态 === '败阵' || row.状态 === '逃走') return []
  return row.状态.split('、').map(value => value.trim()).filter(Boolean)
}

function cooldownTags(row?: ParsedRow): string[] {
  if (!row?.冷却 || row.冷却 === '无') return []
  return row.冷却.split('、').map(value => value.trim()).filter(Boolean)
}

function battleStateStatus(data: any): string {
  return String(data?.战局状态?.状态 || '')
}

function isTerminal(data: any): boolean {
  const status = battleStateStatus(data)
  return data?.界面 === 'battle-end-ui' || Boolean(status && status !== '进行中')
}

function isVictory(data: any): boolean {
  return /我方胜|敌方认输/.test(battleStateStatus(data))
}

function displayRound(data: any): string {
  const round = data?.战局状态?.回合数
  return Number.isFinite(Number(round)) ? `第 ${round} 回合` : ''
}

function actionLabel(entry: BattleEntry): string {
  const actor = entry.行动者 || '未知角色'
  const target = entry.目标 ? ` → ${entry.目标}` : ''
  if (entry.类型 === '武学') return `${actor}施展【${entry.技能 || '武学'}${entry.招式 ? `·${entry.招式}` : ''}】${target}`
  if (entry.类型 === '物品') return `${actor}使用【${String((entry as any).物品 || '物品')}】${target}`
  if (entry.类型 === '休息') return `${actor}敛气调息`
  if (entry.类型 === '逃跑') return `${actor}${entry.逃跑成功 ? '成功脱身' : '试图脱身'}`
  if (entry.类型 === '认输') return `${actor}认输`
  if (entry.类型 === '运功') return `${actor}运功凝神`
  return `${actor}行动`
}

function hpDelta(entry: BattleEntry): string {
  const changes: string[] = []
  const add = (target: string | undefined, value: any) => {
    const values = Array.isArray(value) ? value : value ? [value] : []
    for (const change of values) {
      if (change?.原值 == null || change?.新值 == null) continue
      const delta = Number(change.新值) - Number(change.原值)
      if (delta) changes.push(`${target || '目标'}气血${delta > 0 ? '+' : ''}${delta}`)
    }
  }
  add(entry.目标, entry.目标气血变化)
  for (const target of entry.目标结算 || []) add(target.目标, target.目标气血变化)
  add(entry.行动者, entry.行动者气血变化)
  add(entry.行动者, entry.气血变化)
  return changes.join(' · ')
}

function targetNames(entry: BattleEntry | null): Set<string> {
  const result = new Set<string>()
  if (!entry) return result
  if (entry.目标) result.add(entry.目标)
  for (const target of entry.目标结算 || []) if (target.目标) result.add(target.目标)
  return result
}

function actionError(data: any): string | null {
  const error = engineError(data)
  if (error) return error
  if (data?.界面 !== 'battle-ui' && data?.界面 !== 'battle-end-ui') {
    return `engine 未返回战斗界面（实际：${String(data?.界面 || '无界面')}）`
  }
  return null
}

function skillReasons(skill: ParsedSkill): string {
  if (skill.flags) return skill.flags.filter(flag => flag !== '可用').join('、')
  return [
    skill.冷却中 ? `冷却中（剩${skill.冷却剩余 || 0}回合）` : '',
    skill.内力不足 ? '内力不足' : '',
    skill.武器不符 ? '武器不符' : '',
  ].filter(Boolean).join('、')
}

function CardBar({ kind, value }: { kind: 'hp' | 'mp'; value?: string }) {
  const parsed = barValues(value)
  const label = kind === 'hp' ? '气血' : '内力'
  const color = kind === 'mp' ? '#3a5a8a' : parsed && parsed.percent < 35 ? '#a83232' : '#8a4a3a'
  return (
    <div className={kind === 'hp' && parsed && parsed.percent < 35 ? 'wbc-low-bar' : undefined} style={{
      position: 'relative', height: 15, overflow: 'hidden', borderRadius: 3,
      border: `1px solid ${BORDER_COLOR}`, background: '#0f0d0a',
    }}>
      <div style={{ position: 'absolute', inset: 0, width: `${parsed?.percent ?? 0}%`, background: color, transition: 'width 240ms ease' }} />
      <span style={{
        position: 'absolute', inset: 0, display: 'flex', alignItems: 'center', justifyContent: 'center',
        color: '#fff', fontSize: 9.5, textShadow: '0 1px 2px #000',
      }}>
        {label} {parsed ? `${parsed.current}/${parsed.maximum}` : '—'}
      </span>
    </div>
  )
}

function FighterCard({
  name, tag, side, row, display, actor, highlighted, targetable, onTarget, cardRef,
}: {
  name: string
  tag: string
  side: Side
  row?: ParsedRow
  display?: FighterDisplay
  actor: boolean
  highlighted: boolean
  targetable: boolean
  onTarget: () => void
  cardRef: (node: HTMLButtonElement | null) => void
}) {
  const dead = display?.dead ?? Boolean(/败阵/.test(tag) || row?.败阵 || row?.状态列 === '败阵' || row?.状态 === '败阵')
  const fled = display?.fled ?? Boolean(/逃走/.test(tag) || row?.逃走 || row?.状态列 === '逃走' || row?.状态 === '逃走')
  const states = display?.statuses ?? statusTags(row)
  const cooldowns = display?.cooldowns ?? cooldownTags(row)
  const sideColor = side === 'ally' ? ALLY_COLOR : ENEMY_COLOR
  const border = targetable ? OK_COLOR : actor ? TITLE_COLOR : highlighted ? DANGER_COLOR : BORDER_COLOR
  return (
    <button
      ref={cardRef}
      type="button"
      data-side={side}
      disabled={!targetable}
      onClick={targetable ? onTarget : undefined}
      style={{
        position: 'relative', flex: `0 0 ${FIGHTER_CARD_WIDTH}px`,
        width: FIGHTER_CARD_WIDTH, height: FIGHTER_CARD_HEIGHT,
        boxSizing: 'border-box', padding: '9px 10px 8px', textAlign: 'left',
        border: `1px solid ${border}`, borderRadius: 8, background: '#1d1813', color: '#e8dcc4',
        opacity: dead || fled ? 0.42 : 1, cursor: targetable ? 'pointer' : 'default',
        boxShadow: actor ? '0 0 13px rgba(200,164,86,0.32)' : highlighted ? '0 0 11px rgba(215,123,111,0.28)' : 'none',
        transform: actor ? 'translateY(-2px)' : 'none', transition: 'all 180ms ease', fontFamily: 'inherit',
      }}
    >
      <div style={{ display: 'flex', alignItems: 'baseline', gap: 6, minWidth: 0, height: 19, overflow: 'hidden' }}>
        <span title={name} style={{ flex: '1 1 auto', minWidth: 0, color: sideColor, fontSize: 13.5, whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis' }}>{name}</span>
        <span style={{ flex: '0 0 auto', color: DIM_COLOR, fontSize: 9.5 }}>{fled ? '逃走' : dead ? '败阵' : tag && tag !== '战斗中' ? tag : ''}</span>
      </div>
      <div style={{ display: 'grid', gap: 4, marginTop: 6 }}>
        <CardBar kind="hp" value={display?.hp ?? row?.气血} />
        <CardBar kind="mp" value={display?.mp ?? row?.内力} />
      </div>
      {(states.length > 0 || cooldowns.length > 0) ? (
        <div title={[...states, ...cooldowns].join('、')} style={{ display: 'flex', flexWrap: 'wrap', gap: 3, minHeight: 5, maxHeight: 28, overflow: 'hidden', marginTop: 6 }}>
          {states.map((state, index) => (
            <span className="wbc-status-badge" key={`s:${state}:${index}`} style={{ padding: '0 5px', border: '1px solid #795f2c', borderRadius: 7, color: TITLE_COLOR, fontSize: 9 }}>
              {state}
            </span>
          ))}
          {cooldowns.map((cooldown, index) => (
            <span className="wbc-status-badge" key={`c:${cooldown}:${index}`} style={{ padding: '0 5px', border: `1px solid ${BORDER_COLOR}`, borderRadius: 7, color: DIM_COLOR, fontSize: 9 }}>
              {cooldown}
            </span>
          ))}
        </div>
      ) : null}
      {targetable ? (
        <span style={{ position: 'absolute', top: -8, right: 7, padding: '0 6px', borderRadius: 7, background: OK_COLOR, color: '#111', fontSize: 9 }}>
          选择目标
        </span>
      ) : actor ? (
        <span style={{ position: 'absolute', top: -8, right: 7, padding: '0 6px', borderRadius: 7, background: TITLE_COLOR, color: '#21180c', fontSize: 9 }}>
          行动中
        </span>
      ) : null}
    </button>
  )
}

function Formation({
  label, side, roster, parse, display, pick, replayEntry, onTarget, registerFighter,
}: {
  label: string
  side: Side
  roster: { name: string; tag: string }[]
  parse: ParsedAction
  display: Record<string, FighterDisplay>
  pick: TargetPick | null
  replayEntry: BattleEntry | null
  onTarget: (name: string) => void
  registerFighter: (name: string, node: HTMLButtonElement | null) => void
}) {
  const targets = targetNames(replayEntry)
  const sideLabel = (
    <div style={{
      color: side === 'ally' ? ALLY_COLOR : ENEMY_COLOR,
      fontSize: 11,
      letterSpacing: 4,
      textAlign: 'center',
      ...(side === 'ally' ? { marginTop: 7 } : { marginBottom: 7 }),
    }}>
      {label}
    </div>
  )
  return (
    <section>
      {side === 'enemy' ? sideLabel : null}
      <div style={{ display: 'flex', justifyContent: 'center', alignItems: 'flex-start', flexWrap: 'wrap', gap: 9 }}>
        {roster.map(character => {
          const row = parse.table[character.name]
          const dead = /败阵/.test(character.tag) || row?.败阵 || row?.状态列 === '败阵'
          const fled = /逃走/.test(character.tag) || row?.逃走 || row?.状态列 === '逃走'
          const actor = replayEntry?.行动者 === character.name
          const currentActor = parse.actor === character.name
          const targetable = Boolean(
            pick && pick.side === side && !dead && !fled && !(pick.noSelf && currentActor),
          )
          return (
            <FighterCard
              key={character.name}
              name={character.name}
              tag={character.tag}
              side={side}
              row={row}
              display={display[character.name]}
              actor={actor}
              highlighted={targets.has(character.name)}
              targetable={targetable}
              onTarget={() => onTarget(character.name)}
              cardRef={node => registerFighter(character.name, node)}
            />
          )
        })}
      </div>
      {side === 'ally' ? sideLabel : null}
    </section>
  )
}

function ActionChain({ data, parse, replayEntry }: { data: any; parse: ParsedAction; replayEntry: BattleEntry | null }) {
  const allies = new Set(rosterParse(data?.战局状态?.我方).map(item => item.name))
  const declared = Array.isArray(data?.行动预告) ? data.行动预告.map(String) : []
  const sequence: string[] = []
  const current = replayEntry?.行动者 || parse.actor
  if (current) sequence.push(current)
  for (const name of declared.length ? declared : parse.order) {
    if (name && !sequence.includes(name)) sequence.push(name)
  }
  if (!sequence.length) {
    for (const item of [
      ...rosterParse(data?.战局状态?.我方),
      ...rosterParse(data?.战局状态?.敌方),
    ]) if (!sequence.includes(item.name)) sequence.push(item.name)
  }
  const shown = sequence.slice(0, 7)
  return (
    <div style={{
      display: 'flex', alignItems: 'center', gap: 6, overflowX: 'auto', padding: '8px 10px',
      borderTop: `1px solid ${BORDER_COLOR}`, borderBottom: '1px solid #6f5527',
      background: 'linear-gradient(90deg,#181310,#2c2010 22%,#2c2010 78%,#181310)',
    }}>
      <span style={{ flex: '0 0 auto', paddingRight: 10, borderRight: `1px solid ${BORDER_COLOR}`, color: TITLE_COLOR, fontSize: 10.5, letterSpacing: 2 }}>
        行 动 预 告
      </span>
      {shown.map((name, index) => (
        <span key={`${name}:${index}`} style={{ display: 'contents' }}>
          <span style={{
            flex: '0 0 auto', padding: index === 0 ? '4px 12px' : '3px 9px', borderRadius: 12,
            border: `1px solid ${index === 0 ? TITLE_COLOR : BORDER_COLOR}`,
            background: index === 0 ? 'linear-gradient(180deg,#d8b466,#b8923c)' : 'rgba(0,0,0,0.22)',
            color: index === 0 ? '#1a1208' : allies.has(name) ? ALLY_COLOR : ENEMY_COLOR,
            fontWeight: index === 0 ? 700 : 400, fontSize: index === 0 ? 12.5 : 11,
          }}>
            {name}
          </span>
          {index < shown.length - 1 ? <span style={{ flex: '0 0 auto', color: '#795f2c' }}>→</span> : null}
        </span>
      ))}
      {sequence.length > shown.length ? <span style={{ color: DIM_COLOR, fontSize: 10 }}>+{sequence.length - shown.length}</span> : null}
    </div>
  )
}

function ReplayBanner({ entry, index, total, skipped }: {
  entry: BattleEntry | null
  index: number
  total: number
  skipped: number
}) {
  if (!entry) return null
  const delta = hpDelta(entry)
  return (
    <div style={{
      margin: '10px 12px 0', padding: '8px 10px', border: '1px solid #795f2c', borderRadius: 7,
      background: 'rgba(200,164,86,0.09)', color: '#e8dcc4', fontSize: 11.5,
    }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', gap: 8, color: TITLE_COLOR }}>
        <span>{actionLabel(entry)}</span>
        <span style={{ flex: '0 0 auto', color: DIM_COLOR }}>{index}/{total}</span>
      </div>
      {delta ? <div style={{ marginTop: 3, color: DANGER_COLOR }}>{delta}</div> : null}
      {skipped > 0 && index === 1 ? (
        <div style={{ marginTop: 3, color: DIM_COLOR, fontSize: 10 }}>
          AI 自动战斗较长，已略过前 {skipped} 条动画；完整战报仍保留在下方。
        </div>
      ) : null}
    </div>
  )
}

function skillTip(skill: ParsedSkill): string {
  const unavailable = !skill.可用
  return [
    `【${skill.名称}】`,
    `${skill.类型 || '武学'} · ${skill.范围 || '敌方单体'}`,
    `威力${String(skill.威力)} · 内力${String(skill.内力)} · 冷却${String(skill.冷却)}`,
    skill.特效 ? `特效：${skill.特效}` : '',
    unavailable ? `当前不可用：${skillReasons(skill) || '条件不满足'}` : '',
  ].filter(Boolean).join('\n')
}

function itemTip(item: ParsedItem): string {
  return [
    `【${item.名称}】 ×${item.数量}`,
    item.效果 ? `效果：${item.效果}` : '',
    item.方向 ? `方向：${item.方向}` : '',
  ].filter(Boolean).join('\n')
}

function SkillCard({ skill, picked, disabled, onClick, onTip }: {
  skill: ParsedSkill
  picked: boolean
  disabled: boolean
  onClick: () => void
  onTip: (value: string) => void
}) {
  const unavailable = !skill.可用
  const inert = disabled || unavailable
  const tip = skillTip(skill)
  return (
    <button
      type="button"
      aria-disabled={inert}
      onMouseEnter={() => onTip(tip)}
      onMouseLeave={() => onTip('')}
      onFocus={() => onTip(tip)}
      onBlur={() => onTip('')}
      onClick={inert ? undefined : () => { onTip(''); onClick() }}
      style={{
        display: 'grid', gridTemplateRows: '1fr 1fr', alignItems: 'center', gap: 2,
        flex: '1 1 0', minWidth: 0, height: 46, padding: '5px 6px', textAlign: 'center', borderRadius: 6,
        border: `1px solid ${picked ? OK_COLOR : unavailable ? BORDER_COLOR : '#795f2c'}`,
        background: picked ? '#21301d' : '#1d1813', color: '#e8dcc4',
        cursor: inert ? 'default' : 'pointer', opacity: unavailable ? 0.48 : disabled ? 0.58 : 1,
        fontFamily: 'inherit', transition: 'all 140ms ease',
      }}
    >
      <span style={{ minWidth: 0, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap', color: unavailable ? DIM_COLOR : TITLE_COLOR, fontSize: 10.5 }}>
        {skill.名称}
      </span>
      <span style={{ minWidth: 0, color: DIM_COLOR, fontSize: 9 }}>内力 {String(skill.内力)}</span>
    </button>
  )
}

function ItemCard({ item, picked, disabled, onClick, onTip }: {
  item: ParsedItem
  picked: boolean
  disabled: boolean
  onClick: () => void
  onTip: (value: string) => void
}) {
  const inert = disabled || item.数量 < 1
  const tip = itemTip(item)
  return (
    <button
      type="button"
      aria-disabled={inert}
      onMouseEnter={() => onTip(tip)}
      onMouseLeave={() => onTip('')}
      onFocus={() => onTip(tip)}
      onBlur={() => onTip('')}
      onClick={inert ? undefined : () => { onTip(''); onClick() }}
      style={{
        display: 'grid', gridTemplateRows: '1fr 1fr', alignItems: 'center', gap: 2,
        flex: '1 1 0', minWidth: 0, height: 46, padding: '5px 6px', textAlign: 'center', borderRadius: 6,
        border: `1px solid ${picked ? OK_COLOR : '#795f2c'}`,
        background: picked ? '#21301d' : '#1d1813', color: '#e8dcc4',
        cursor: inert ? 'default' : 'pointer', opacity: inert ? 0.55 : 1,
        fontFamily: 'inherit', transition: 'all 140ms ease',
      }}
    >
      <span style={{ minWidth: 0, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap', color: TITLE_COLOR, fontSize: 10.5 }}>
        {item.名称}
      </span>
      <span style={{ minWidth: 0, color: DIM_COLOR, fontSize: 9 }}>数量 ×{item.数量}</span>
    </button>
  )
}

function TerminalPanel({
  data, busy, submitted, error, onSubmit,
}: {
  data: any
  busy: boolean
  submitted: boolean
  error: string
  onSubmit: (decisions: { 角色: string; 决定: '杀' | '放' }[]) => void
}) {
  const victory = isVictory(data)
  const status = battleStateStatus(data)
  const draw = /平局/.test(status)
  const candidates = Array.isArray(data?.处决候选)
    ? data.处决候选.filter((item: any) => item && typeof item.名称 === 'string')
    : []
  const [picks, setPicks] = useState<Record<string, '杀' | '放'>>({})
  const complete = candidates.every((candidate: any) => picks[candidate.名称])

  return (
    <div style={{ margin: '12px', padding: '16px 15px', border: '1px solid #795f2c', borderRadius: 10, background: '#19140f', textAlign: 'center' }}>
      <div style={{ color: victory || draw ? TITLE_COLOR : DANGER_COLOR, fontSize: 20, letterSpacing: 5, marginBottom: 5 }}>
        {victory ? '大 获 全 胜' : draw ? '难 分 高 下' : '一 败 涂 地'}
      </div>
      <div style={{ color: DIM_COLOR, fontSize: 11.5, lineHeight: 1.65, marginBottom: 11 }}>
        {submitted
          ? '战果已提交，等待 GM 完成战后处置。'
          : victory
            ? candidates.length ? '逐人决定败方处置；逃走者不在候选中。' : '敌方已全数逃走，无可处决对象。'
            : `战报落定（${status || '终局'}），GM 将接续战后剧情。`}
      </div>
      <PanelNotice kind="error">{error}</PanelNotice>
      {victory && !submitted ? candidates.map((candidate: any) => {
        const name = candidate.名称
        return (
          <div key={name} style={{
            display: 'grid', gridTemplateColumns: 'minmax(80px, 1fr) minmax(100px, 2fr) auto auto',
            alignItems: 'center', gap: 7, padding: '7px 8px', margin: '6px 0',
            border: `1px solid ${BORDER_COLOR}`, borderRadius: 7, textAlign: 'left',
          }}>
            <span style={{ color: ENEMY_COLOR, overflowWrap: 'anywhere' }}>{name}</span>
            <span style={{ color: DIM_COLOR, fontSize: 10.5 }}>{String(candidate.状态 || '倒地不起，气息尚存')}</span>
            {(['杀', '放'] as const).map(decision => (
              <button
                key={decision}
                type="button"
                disabled={busy}
                onClick={() => setPicks(value => ({ ...value, [name]: decision }))}
                style={{
                  padding: '3px 11px', borderRadius: 5,
                  border: `1px solid ${picks[name] === decision ? TITLE_COLOR : BORDER_COLOR}`,
                  background: picks[name] === decision ? TITLE_COLOR : '#211b15',
                  color: picks[name] === decision ? '#1a1208' : decision === '杀' ? DANGER_COLOR : OK_COLOR,
                  cursor: busy ? 'default' : 'pointer', fontFamily: 'inherit',
                }}
              >{decision}</button>
            ))}
          </div>
        )
      }) : null}
      {!submitted ? (
        <button
          type="button"
          disabled={busy || (victory && !complete)}
          onClick={() => onSubmit(candidates.map((candidate: any) => ({ 角色: candidate.名称, 决定: picks[candidate.名称] }))) }
          style={{
            width: '100%', marginTop: 9, padding: '9px 12px', border: 0, borderRadius: 7,
            background: 'linear-gradient(180deg,#c8a456,#9a7830)', color: '#1a1208',
            opacity: busy || (victory && !complete) ? 0.45 : 1,
            cursor: busy || (victory && !complete) ? 'default' : 'pointer',
            fontWeight: 600, letterSpacing: 2, fontFamily: 'inherit',
          }}
        >
          {busy ? '正在提交…' : victory ? candidates.length ? '镌 定 裁 决' : '继 续 战 后 处 置' : '确 认 战 果 · 静 候 处 置'}
        </button>
      ) : (
        <div style={{ padding: '7px 10px', borderRadius: 6, background: '#172316', color: '#a9c98a', fontSize: 11.5 }}>
          ✓ 已交由 GM 处理
        </div>
      )}
    </div>
  )
}

/** dsh conversation 专用战斗 Card：本地持有并原位替换每轮 battle-ui。 */
export function BattleCard({ initialData, battleRequest, locked }: {
  initialData: Record<string, any>
  battleRequest?: BattleRequest
  /** 所属回合已被新回合取代：过时快照，操作禁用、仅供回顾（战报日志仍可滚动） */
  locked?: boolean
}) {
  const [data, setData] = useState<Record<string, any>>(initialData)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const [pendingAdvance, setPendingAdvance] = useState(false)
  const [pick, setPick] = useState<TargetPick | null>(null)
  const [confirmSurrender, setConfirmSurrender] = useState(false)
  const [submitted, setSubmitted] = useState(false)
  const [actionTip, setActionTip] = useState('')
  const requestId = useRef(0)

  const parse = useMemo(() => battleParse(data), [data])
  const allies = useMemo(() => rosterParse(data?.战局状态?.我方), [data])
  const enemies = useMemo(() => rosterParse(data?.战局状态?.敌方), [data])
  const details = useMemo(
    () => Array.isArray(data?.回合详情) ? data.回合详情 as BattleEntry[] : [],
    [data],
  )
  const {
    display, replayEntry, replayIndex, replayTotal, replaySkipped, replaying,
    rootRef, overlayRef, registerFighter,
  } = useCardBattleReplay(parse, details)

  const slot = (() => {
    const fromCard = Number(data?.槽位)
    if (Number.isInteger(fromCard) && fromCard > 0) return fromCard
    return useParty.getState().slot
  })()
  const terminal = isTerminal(data)
  const interactionLocked = busy || replaying || pendingAdvance || terminal || Boolean(locked)
  const actorIsAlly = Boolean(parse.actor && allies.some(character => character.name === parse.actor))
  const usable = !interactionLocked && actorIsAlly

  const applyResult = (result: Record<string, any>) => {
    const failure = actionError(result)
    if (failure) throw new Error(failure)
    setPick(null)
    setPendingAdvance(false)
    setError('')
    setData(current => ({
      ...result,
      ...(result.允许逃跑 === undefined && current.允许逃跑 !== undefined
        ? { 允许逃跑: current.允许逃跑 }
        : {}),
      ...(result.操控方式 === undefined && current.操控方式 !== undefined
        ? { 操控方式: current.操控方式 }
        : {}),
      ...(result.槽位 === undefined && current.槽位 !== undefined
        ? { 槽位: current.槽位 }
        : {}),
    }))
  }

  const performAction = async (action: Record<string, unknown>) => {
    if (busy || pendingAdvance || replaying || terminal) return
    if (!battleRequest || slot == null) {
      setError(battleRequest ? '当前 Battle Card 缺少有效存档槽位' : '当前会话暂不可调用战斗功能')
      return
    }
    const currentRequest = ++requestId.current
    setBusy(true)
    setPick(null)
    setConfirmSurrender(false)
    setError('')
    try {
      const response = await battleRequest({ operation: 'act', slot, action })
      if (currentRequest !== requestId.current) return
      const result = response.result
      const failure = actionError(result)
      if (failure) {
        // Host 明确 committed=false 时 go 未落盘，允许玩家修正后重试原动作。
        setPendingAdvance(response.pendingAdvance === true || response.committed === true)
        setError(failure)
        return
      }
      applyResult(result!)
    } catch (caught) {
      if (currentRequest !== requestId.current) return
      // 传输中断无法确认 go 是否已落盘，保守锁定新动作，仅允许同步 battle_last。
      setPendingAdvance(true)
      setError(caught instanceof Error ? caught.message : String(caught))
    } finally {
      if (currentRequest === requestId.current) setBusy(false)
    }
  }

  const retryAdvance = async () => {
    if (busy || !pendingAdvance) return
    if (!battleRequest || slot == null) {
      setError(battleRequest ? '当前 Battle Card 缺少有效存档槽位' : '当前会话暂不可调用战斗功能')
      return
    }
    const currentRequest = ++requestId.current
    setBusy(true)
    setError('')
    try {
      const response = await battleRequest({ operation: 'advance', slot })
      if (currentRequest !== requestId.current) return
      const result = response.result
      const failure = actionError(result)
      if (failure) {
        if (/无可推进的战斗|未找到/.test(failure)) setPendingAdvance(false)
        throw new Error(failure)
      }
      applyResult(result!)
    } catch (caught) {
      if (currentRequest !== requestId.current) return
      setError(caught instanceof Error ? caught.message : String(caught))
    } finally {
      if (currentRequest === requestId.current) setBusy(false)
    }
  }

  const chooseSkill = (skill: ParsedSkill) => {
    if (!usable || !skill.可用) return
    setConfirmSurrender(false)
    if (skill.范围 === '敌方全体') {
      void performAction({ 类型: '战斗-使用武学', 武学: skill.名称 })
      return
    }
    setPick({
      kind: 'skill', name: skill.名称,
      side: /^我方/.test(skill.范围 || '') ? 'ally' : 'enemy',
      noSelf: skill.范围 === '我方单体除自身',
    })
  }

  const chooseItem = (item: ParsedItem) => {
    if (!usable || item.数量 < 1) return
    setConfirmSurrender(false)
    setPick({
      kind: 'item', name: item.名称,
      side: item.方向 === '对我方' ? 'ally' : 'enemy',
      noSelf: false,
    })
  }

  const resolveTarget = (target: string) => {
    if (!pick) return
    const action = pick.kind === 'skill'
      ? { 类型: '战斗-使用武学', 武学: pick.name, 目标: target }
      : { 类型: '战斗-使用物品', 物品: pick.name, 目标: target }
    setPick(null)
    void performAction(action)
  }

  const submitConclusion = async (decisions: { 角色: string; 决定: '杀' | '放' }[]) => {
    if (busy || submitted) return
    if (!battleRequest || slot == null) {
      setError(battleRequest ? '当前 Battle Card 缺少有效存档槽位' : '当前会话暂不可提交战果')
      return
    }
    const currentRequest = ++requestId.current
    setBusy(true)
    setError('')
    try {
      const response = await battleRequest({
        operation: 'conclude',
        slot,
        final: {
          战局状态: data.战局状态,
          战果: data.战果,
          经验结算: data.经验结算,
          处决候选: data.处决候选,
        },
        decisions,
      })
      if (currentRequest !== requestId.current) return
      if (!response.followup) throw new Error('战果已提交，但未能唤起 GM 战后处置')
      setSubmitted(true)
      // 玩家已确认战后结算，恢复队伍状态浮窗
      useBattleMode.getState().clear()
    } catch (caught) {
      if (currentRequest !== requestId.current) return
      setError(caught instanceof Error ? caught.message : String(caught))
    } finally {
      if (currentRequest === requestId.current) setBusy(false)
    }
  }

  let turnText = '◌ 战局推演中…'
  if (terminal) turnText = '—— 战局已终'
  else if (parse.actor) turnText = actorIsAlly ? `▶ 轮到 ${parse.actor}` : `◌ ${parse.actor} 行动中…`
  const shownSkills = parse.skills.slice(0, 4)
  const shownItems = parse.items.slice(0, 4)

  return (
    <div ref={rootRef} className="wuxia-battle-card" title={locked ? '回合已推进，此卡仅供回顾' : undefined} style={{
      ...CARD_STYLE,
      padding: 0,
      position: 'relative',
      overflow: 'hidden',
      maxWidth: '100%',
      background: 'radial-gradient(700px 260px at 50% -100px,rgba(120,40,40,.16),transparent 62%),#16120e',
    }}>
      <style>{`
        @keyframes wbcBadgeIn { from { opacity: 0; transform: scale(.55); } to { opacity: 1; transform: scale(1); } }
        @keyframes wbcLowPulse { 50% { filter: brightness(1.5); } }
        .wuxia-battle-card .wbc-status-badge { animation: wbcBadgeIn .32s ease-out both; }
        .wuxia-battle-card .wbc-low-bar { animation: wbcLowPulse 1.6s ease-in-out infinite; }
      `}</style>
      <div ref={overlayRef} aria-hidden="true" style={{ position: 'absolute', inset: 0, zIndex: 40, overflow: 'hidden', pointerEvents: 'none' }} />
      {/* 锁定时不整体置灰：战报/阵容等文字保持亮色，操作按钮经 usable/TerminalPanel busy 各自变灰 */}
      <div style={{ display: 'flex', alignItems: 'center', flexWrap: 'wrap', gap: 9, padding: '9px 13px', background: 'linear-gradient(180deg,#241a10,#15110d)', borderBottom: `1px solid ${BORDER_COLOR}` }}>
        <span style={{ color: '#e8dcc4', fontSize: 15, fontWeight: 600, letterSpacing: 2 }}><em style={{ color: DANGER_COLOR, fontStyle: 'normal', marginRight: 6 }}>⚔</em>遭遇战</span>
        {displayRound(data) ? <span style={{ padding: '1px 8px', border: `1px solid ${BORDER_COLOR}`, borderRadius: 9, color: DIM_COLOR, fontSize: 10 }}>{displayRound(data)}</span> : null}
        <span style={{ padding: '1px 8px', border: `1px solid ${BORDER_COLOR}`, borderRadius: 9, color: terminal ? isVictory(data) ? TITLE_COLOR : DANGER_COLOR : OK_COLOR, fontSize: 10 }}>
          {battleStateStatus(data) || '进行中'}
        </span>
        <span style={{ marginLeft: 'auto', color: DIM_COLOR, fontSize: 10.5 }}>{turnText}</span>
      </div>

      <ActionChain data={data} parse={parse} replayEntry={replayEntry} />
      <ReplayBanner entry={replayEntry} index={replayIndex} total={replayTotal} skipped={replaySkipped} />
      {!terminal ? <PanelNotice kind="error">{error}</PanelNotice> : null}
      {pendingAdvance ? (
        <div style={{ margin: '8px 12px', padding: '8px 10px', border: '1px solid #68352e', borderRadius: 7, background: '#2b1715', color: '#ed998d', fontSize: 11.5 }}>
          本次战斗动作可能已结算，但 Battle Card 更新失败。为避免重复推进，只能先重新同步战局。
          <button
            type="button"
            disabled={busy || Boolean(locked)}
            onClick={() => { void retryAdvance() }}
            style={{ marginLeft: 9, padding: '3px 10px', border: '1px solid #8a6a2a', borderRadius: 5, background: '#2a2318', color: TITLE_COLOR, cursor: busy || locked ? 'default' : 'pointer', fontFamily: 'inherit' }}
          >{busy ? '同步中…' : '重新同步战局'}</button>
        </div>
      ) : null}

      <div style={{ display: 'grid', gap: 42, padding: '15px 12px 18px' }}>
        <Formation label="敌 方" side="enemy" roster={enemies} parse={parse} display={display} pick={pick} replayEntry={replayEntry} onTarget={resolveTarget} registerFighter={registerFighter} />
        <Formation label="我 方" side="ally" roster={allies} parse={parse} display={display} pick={pick} replayEntry={replayEntry} onTarget={resolveTarget} registerFighter={registerFighter} />
      </div>

      {!terminal || replaying ? (
        <section style={{ padding: '11px 12px 13px', borderTop: `1px solid ${BORDER_COLOR}`, background: 'linear-gradient(180deg,#1d1712,#15110d)' }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: 8, flexWrap: 'wrap', marginBottom: 8 }}>
            <span style={{ color: actorIsAlly ? TITLE_COLOR : DIM_COLOR, fontSize: 12 }}>{turnText}</span>
            {pick ? <span style={{ color: OK_COLOR, fontSize: 10.5 }}>请选择{pick.side === 'ally' ? '我方' : '敌方'}目标</span> : null}
            {pick ? (
              <button type="button" onClick={() => setPick(null)} style={{ padding: '2px 8px', border: `1px solid ${BORDER_COLOR}`, borderRadius: 5, background: 'transparent', color: DIM_COLOR, cursor: 'pointer', fontFamily: 'inherit' }}>
                取消选择
              </button>
            ) : null}
          </div>
          <div style={{ position: 'relative' }}>
            {actionTip ? (
              <div style={{
                position: 'absolute', left: '50%', bottom: 'calc(100% + 7px)', zIndex: 55,
                width: 'min(420px, calc(100% - 20px))', transform: 'translateX(-50%)',
                padding: '8px 10px', border: '1px solid #8a6a2a', borderRadius: 7,
                background: '#0f0d0a', boxShadow: '0 5px 18px rgba(0,0,0,.62)',
                color: '#ded0b8', fontSize: 10.5, lineHeight: 1.55, whiteSpace: 'pre-line',
                pointerEvents: 'none',
              }}>
                {actionTip}
              </div>
            ) : null}
            <div style={{ display: 'grid', gridTemplateColumns: 'minmax(0, 1fr) minmax(0, 1fr)', gap: 8, marginBottom: 5 }}>
              <div style={{ color: DIM_COLOR, fontSize: 9.5, letterSpacing: 2 }}>武学</div>
              <div style={{ paddingLeft: 8, borderLeft: `1px solid ${BORDER_COLOR}`, color: DIM_COLOR, fontSize: 9.5, letterSpacing: 2 }}>物品</div>
            </div>
            <div style={{ display: 'flex', alignItems: 'stretch', gap: 8, minWidth: 0 }}>
              <div style={{ display: 'flex', alignItems: 'stretch', gap: 5, flex: '1 1 0', minWidth: 0 }}>
                {[0, 1, 2, 3].map(index => {
                  const skill = shownSkills[index]
                  return skill ? (
                    <SkillCard
                      key={skill.名称}
                      skill={skill}
                      picked={pick?.kind === 'skill' && pick.name === skill.名称}
                      disabled={!usable}
                      onClick={() => chooseSkill(skill)}
                      onTip={setActionTip}
                    />
                  ) : (
                    <span key={`skill-empty:${index}`} style={{ display: 'flex', alignItems: 'center', justifyContent: 'center', flex: '1 1 0', minWidth: 0, height: 46, border: `1px dashed ${BORDER_COLOR}`, borderRadius: 6, color: DIM_COLOR, opacity: 0.5, fontSize: 9 }}>空</span>
                  )
                })}
              </div>
              <div style={{ display: 'flex', alignItems: 'stretch', gap: 5, flex: '1 1 0', minWidth: 0, paddingLeft: 8, borderLeft: `1px solid ${BORDER_COLOR}` }}>
                {[0, 1, 2, 3].map(index => {
                  const item = shownItems[index]
                  return item ? (
                    <ItemCard
                      key={item.名称}
                      item={item}
                      picked={pick?.kind === 'item' && pick.name === item.名称}
                      disabled={!usable}
                      onClick={() => chooseItem(item)}
                      onTip={setActionTip}
                    />
                  ) : (
                    <span key={`item-empty:${index}`} style={{ display: 'flex', alignItems: 'center', justifyContent: 'center', flex: '1 1 0', minWidth: 0, height: 46, border: `1px dashed ${BORDER_COLOR}`, borderRadius: 6, color: DIM_COLOR, opacity: 0.5, fontSize: 9 }}>空</span>
                  )
                })}
              </div>
            </div>
          </div>
          <div style={{ display: 'flex', gap: 6, flexWrap: 'wrap', marginTop: 10 }}>
            <button type="button" disabled={!usable} onClick={() => { void performAction({ 类型: '战斗-休息' }) }} style={{ padding: '6px 11px', border: `1px solid ${BORDER_COLOR}`, borderRadius: 6, background: '#211b15', color: '#e8dcc4', opacity: usable ? 1 : 0.42, cursor: usable ? 'pointer' : 'default', fontFamily: 'inherit' }}>休息（回内力10%）</button>
            <button type="button" disabled={!usable || data.允许逃跑 === false} onClick={() => { void performAction({ 类型: '战斗-逃跑' }) }} style={{ padding: '6px 11px', border: `1px solid ${BORDER_COLOR}`, borderRadius: 6, background: '#211b15', color: '#e8dcc4', opacity: usable && data.允许逃跑 !== false ? 1 : 0.42, cursor: usable && data.允许逃跑 !== false ? 'pointer' : 'default', fontFamily: 'inherit' }}>逃跑</button>
            <button type="button" disabled={!usable} onClick={() => setConfirmSurrender(value => !value)} style={{ padding: '6px 11px', border: `1px solid ${confirmSurrender ? DANGER_COLOR : '#68352e'}`, borderRadius: 6, background: confirmSurrender ? '#351816' : '#211b15', color: DANGER_COLOR, opacity: usable ? 1 : 0.42, cursor: usable ? 'pointer' : 'default', fontFamily: 'inherit' }}>认输</button>
          </div>
          {confirmSurrender ? (
            <div style={{ display: 'flex', alignItems: 'center', flexWrap: 'wrap', gap: 7, marginTop: 8, padding: '7px 9px', border: '1px solid #68352e', borderRadius: 6, background: '#2b1715', color: '#ed998d', fontSize: 10.5 }}>
              <span>认输将立即判我方失败，是否确认？</span>
              <button type="button" disabled={!usable} onClick={() => { void performAction({ 类型: '战斗-认输' }) }} style={{ padding: '3px 10px', border: '1px solid #9a4d43', borderRadius: 5, background: '#4a211d', color: '#f1aaa0', cursor: usable ? 'pointer' : 'default', fontFamily: 'inherit' }}>确认认输</button>
              <button type="button" onClick={() => setConfirmSurrender(false)} style={{ padding: '3px 10px', border: `1px solid ${BORDER_COLOR}`, borderRadius: 5, background: '#211b15', color: DIM_COLOR, cursor: 'pointer', fontFamily: 'inherit' }}>取消</button>
            </div>
          ) : null}
        </section>
      ) : null}

      {typeof data?.战报 === 'string' && data.战报.trim() ? (
        <details open={terminal} style={{ borderTop: `1px solid ${BORDER_COLOR}`, background: '#17130f' }}>
          <summary style={{ padding: '7px 12px', color: DIM_COLOR, cursor: 'pointer', fontSize: 10.5, letterSpacing: 2 }}>本 轮 战 报</summary>
          <div style={{ maxHeight: 280, overflow: 'auto', padding: '8px 12px 11px', borderTop: `1px solid ${BORDER_COLOR}`, color: '#d9cbb2', fontSize: 11.5, lineHeight: 1.75, whiteSpace: 'pre-wrap' }}>
            {data.战报}
          </div>
        </details>
      ) : null}

      {terminal && !replaying ? (
        <TerminalPanel data={data} busy={busy || Boolean(locked)} submitted={submitted} error={error} onSubmit={decisions => { void submitConclusion(decisions) }} />
      ) : null}
    </div>
  )
}
