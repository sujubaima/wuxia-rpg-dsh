// 引擎返回与 UI 状态类型。引擎返回用中文键且形态多变，故以宽松接口 + 索引签名为主。

export type Json = string | number | boolean | null | Json[] | { [k: string]: Json }

/** engine go/judge 返回。界面字段决定路由；其余字段按界面类型不同。 */
export interface EngineResult {
  界面?: string
  错误?: string
  error?: string
  槽位?: number
  next_slot?: number
  错误码?: string
  删除槽位?: number
  当前位置?: string
  时段?: string
  时间?: string
  剩余?: number | null
  体力?: number
  金钱?: number
  剧情描写?: string
  场景要素?: SceneElement[]
  相邻出口?: Exit[]
  当前场景类型?: string
  结算?: Settlement[]
  队伍状态?: MemberStatus[]
  界面渲染?: string
  // 战斗
  战局状态?: BattleState
  回合详情?: BattleEntry[]
  行动信息?: ActionInfo
  玩家界面?: string
  行动预告?: string[]
  处决候选?: ExecCandidate[]
  战果?: Json
  经验结算?: Json
  允许逃跑?: boolean
  // 战前
  我方?: string[]
  敌方?: string[]
  操控选项?: string[]
  提示?: string
  战报?: string
  [k: string]: unknown
}

export interface SpecialCommand {
  名称: string
  可用: boolean
}

export interface SceneElement {
  主体?: string
  描写?: string
  特殊指令?: SpecialCommand[]
  [k: string]: unknown
}

export interface Exit {
  方位?: string
  邻场景?: string
  [k: string]: unknown
}

export interface Settlement {
  ok?: boolean
  msg?: string
  变更?: string
  [k: string]: unknown
}

export interface MemberStatus {
  名称?: string
  气血?: number
  气血上限?: number
  内力?: number
  内力上限?: number
  [k: string]: unknown
}

export interface BattleState {
  回合数?: number
  状态?: string
  我方?: string[]
  敌方?: string[]
  [k: string]: unknown
}

export interface BattleEntry {
  回合?: number
  行动者?: string
  类型?: string
  技能?: string
  招式?: string
  目标?: string
  暴击?: boolean
  闪避?: boolean
  目标结算?: TargetSettle[]
  目标气血变化?: HpChange | HpChange[]
  目标内力变化?: HpChange | HpChange[]
  行动者内力变化?: HpChange
  行动者气血变化?: HpChange
  施加状态?: StatusChange[]
  状态失效?: { 名称?: string }[]
  获得状态?: string[]
  状态快照?: Record<string, string[]>
  逃跑成功?: boolean
  内力变化?: HpChange
  气血变化?: HpChange
  [k: string]: unknown
}

export interface TargetSettle {
  目标?: string
  闪避?: boolean
  目标气血变化?: HpChange | HpChange[]
  目标内力变化?: HpChange | HpChange[]
  施加状态?: StatusChange[]
  [k: string]: unknown
}

export interface HpChange {
  原值?: number
  新值?: number
}

export interface StatusChange {
  目标?: string
  名称?: string
}

export interface ExecCandidate {
  名称?: string
  [k: string]: unknown
}

export interface ActionInfo {
  行动者?: string
  行动顺序?: string[]
  状态表?: StatusRow[]
  可用武学?: SkillInfo[]
  可用物品?: ItemInfo[]
  [k: string]: unknown
}

export interface StatusRow {
  名称?: string
  阵营?: string
  气血?: { 当前: number; 上限: number }
  内力?: { 当前: number; 上限: number }
  状态?: string[]
  冷却?: string[]
  败阵?: boolean
  逃走?: boolean
  [k: string]: unknown
}

export interface SkillInfo {
  名称?: string
  类型?: string
  范围?: string
  威力?: string | number
  内力?: string | number
  冷却?: string | number
  可用?: boolean
  冷却中?: boolean
  冷却剩余?: number
  内力不足?: boolean
  武器不符?: boolean
  特效?: string
  [k: string]: unknown
}

export interface ItemInfo {
  名称?: string
  数量?: number
  效果?: string
  方向?: string
  [k: string]: unknown
}

/** 解析后的玩家可操作信息（parseActionInfo/parsePlayerUI 同形）。 */
export interface ParsedAction {
  actor: string | null
  order: string[]
  table: Record<string, ParsedRow>
  skills: ParsedSkill[]
  items: ParsedItem[]
}

export interface ParsedRow {
  阵营?: string
  名称?: string
  气血?: string
  内力?: string
  状态?: string
  冷却?: string
  状态列?: string
  败阵?: boolean
  逃走?: boolean
}

export interface ParsedSkill {
  名称: string
  类型: string
  范围: string
  威力: string | number
  内力: string | number
  冷却: string | number
  可用: boolean
  冷却中?: boolean
  冷却剩余?: number
  内力不足?: boolean
  武器不符?: boolean
  特效?: string
  flags?: string[]
}

export interface ParsedItem {
  名称: string
  数量: number
  效果?: string
  方向?: string
}

/** 聊天消息（游历流 + 日志持久化）。 */
export type Seg = { kind: 'text'; text: string } | { kind: 'tool'; name: string }
export interface ChatMessage {
  role: 'user' | 'assistant'
  text?: string
  segs?: Seg[]
}

export type TabKey = 'travel' | 'bag' | 'equip' | 'wuxue' | 'map' | 'clue' | 'char' | 'save'

export type UiModalKind = 'trade-buy-ui' | 'trade-sell-ui' | 'travel-ui' | 'inn-ui'
export interface UiModalState {
  kind: UiModalKind
  data: EngineResult
}

export interface Toast {
  id: number
  text: string
  cls?: string
}

export interface WaitLine {
  id: number
  summary: string
  detail?: string
}

export interface DisplayState {
  hp: number
  mp: number
  maxhp: number
  maxmp: number
}

export interface BPick {
  kind: 'skill' | 'item'
  name: string
  dir: '我方' | '敌方'
  noSelf: boolean
}

/** go 行为条目（宽松，引擎数据形态多变）。 */
// eslint-disable-next-line @typescript-eslint/no-explicit-any
export type Action = Record<string, any>
