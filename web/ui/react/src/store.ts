// 全局状态与 actions，忠实映射原 9 个 JS 文件的全局 let 与函数。
import { create } from 'zustand'
import { engineGo, engineJudge, fetchUi, setSlotRef, streamChat } from './api'
import { parseActionInfo, parsePlayerUI, rosterParse } from './lib/battleParse'
import type {
  Action, BPick, ChatMessage, DisplayState, EngineResult, MemberStatus, ParsedAction,
  SceneElement, Seg, TabKey, Toast, UiModalKind, UiModalState, WaitLine,
} from './types'

const SLOT_KEY = 'wuxia_newui_slot'
const SID_KEY = 'wuxia_sid'
const LOG_KEY = 'wuxia_log'
const PENDING_BATTLE = 'wuxia_pending_battle'

const HB_ICON: Record<string, string> = { 白天: '☀', 清晨: '☀', 傍晚: '☾', 夜晚: '☾' }

let toastSeq = 1
let waitSeq = 1

export interface GateSave {
  slot: number
  角色名?: string
  最近存档?: string
  saves?: { 序号?: number; 时间戳?: string; label?: string }[]
}

export interface HeadbandState {
  region: string
  scene: string
  clock: string
  icon: string
  cal: string
  saveRemain: string | null
}

export interface StageState {
  narration: string
  changes: string[]
  // 展开后的内容
  elements: { 主体: string; 描写: string; 特殊指令: { 名称: string; 可用: boolean }[] | null }[]
  exits: { 方位: string; 邻场景: string }[]
  hasContent: boolean
}

interface GameState {
  // session
  sessionId: string
  busy: boolean
  cardBusy: boolean
  pendingUser: string | null
  // slot
  currentSlot: number
  selectedMember: string | null
  // gate
  gateMode: boolean
  gateSaves: GateSave[]
  gateSaveCnt: number
  gateLoading: boolean
  // explore
  lastExpl: EngineResult | null
  party: { 体力: number | null; 金钱: number | null; 队伍状态: MemberStatus[] } | null
  headband: HeadbandState
  stage: StageState | null
  stageExpanded: boolean
  prevSceneKey: string | null
  lastStageSig: string
  // battle
  inBattle: boolean
  lastBattle: EngineResult | null
  lastParse: ParsedAction | null
  bPick: BPick | null
  bEnded: boolean
  displayState: Record<string, DisplayState>
  lastOrder: string[]
  lastPlayedRound: number
  battleSeq: number // 自增，驱动回放 hook
  preFight: EngineResult | null
  battleEnd: EngineResult | null
  replayLock: boolean
  replayChain: string[] | null // 回放中逐帧的行动预告顺序；null=非回放，用静态 lastOrder/lastParse
  // tabs
  activeTab: TabKey
  // chat
  messages: ChatMessage[]
  // turn rhythm: -1 灭 / 1 结算 / 2 判盘 / 3 运笔
  steps: number
  turnTools: number
  // ui
  modal: UiModalState | null
  wizardOpen: boolean
  toasts: Toast[]
  waitLines: WaitLine[]
  composerDraft: string

  // ---- actions ----
  setSlot: (v: number) => void
  syncSlot: (d: EngineResult | null) => void
  enterGate: () => void
  enterGame: () => void
  loadGateSaves: () => Promise<void>
  applyExplorationState: (d: EngineResult) => void
  renderParty: (d: EngineResult | null) => void
  refreshParty: () => Promise<void>
  composeExploration: (d: EngineResult) => string
  addGmBlockText: (text: string) => void
  setSteps: (idx: number) => void
  waitAppend: (text: string, detail?: string) => void
  addSysLine: (text: string, opts?: { long?: boolean; cls?: string; replace?: boolean }) => void
  removeToast: (id: number) => void
  openUiModal: (kind: UiModalKind, d: EngineResult) => boolean
  closeUiModal: () => void
  setActiveTab: (t: TabKey) => void
  setSelectedMember: (n: string | null) => void
  openWizard: () => void
  closeWizard: () => void
  setBPick: (p: BPick | null) => void
  setComposerDraft: (v: string) => void
  // 战斗
  enterBattle: (d: EngineResult) => void
  exitBattle: () => void
  setBattleDisplay: (fn: (s: Record<string, DisplayState>) => void) => void
  setBattleEnd: (d: EngineResult | null) => void
  setReplayLock: (v: boolean) => void
  setLastPlayedRound: (n: number) => void
  setReplayChain: (seq: string[] | null) => void
  battleAct: (action: Action) => Promise<void>
  pickBattleTarget: (kind: 'skill' | 'item', obj: { 名称: string; 范围?: string; 方向?: string }) => void
  resolveBattleAction: (target: string) => void
  startBattle: (d: EngineResult, ctrl: string) => Promise<void>
  // 路由
  routeUi: (d: EngineResult, ctx?: { from?: string; showExpl?: boolean }) => boolean
  handleStateEvent: (d: EngineResult) => void
  // 引擎调用包装（供组件复用原 uiOp/elemCmdGo/uiModalGo 语义）
  uiOp: (action: Action, opts?: { confirm?: string; refresh?: () => Promise<void>; reload?: boolean; showExpl?: boolean; slot?: number }) => Promise<EngineResult | null>
  elemCmdGo: (cmd: string, subject: string, merchant: boolean) => Promise<void>
  uiModalGo: (action: Action) => Promise<void>
  notifyGmJudge: (action: Action, d: EngineResult) => void
  // 聊天
  send: (msg?: string, opts?: { hidden?: boolean }) => Promise<void>
  sendHidden: (msg: string) => void
  sendLoadArchive: (slot: number, target: string, label: string) => void
  saveLog: (userText: string | null, segs: Seg[]) => void
  loadLog: () => void
  // 启动
  boot: () => void
}

function readSlot(): number {
  return parseInt(sessionStorage.getItem(SLOT_KEY) || '0', 10) || 0
}
function persistLog(messages: ChatMessage[]): void {
  try {
    sessionStorage.setItem(LOG_KEY, JSON.stringify(messages))
  } catch {
    /* ignore */
  }
}
function cleanSegs(segs: Seg[]): Seg[] {
  return segs.map(s => (s.kind === 'text' ? { kind: 'text', text: s.text } : { kind: 'tool', name: s.name }))
}

const DIR_RE = /^(西北|北|东北|西|东|西南|南|东南)（通往.+）$/
function normEl(f: SceneElement): { 主体: string; 描写: string; 特殊指令: { 名称: string; 可用: boolean }[] | null } {
  if (f && typeof f === 'object') {
    const raw = f.特殊指令
    const cmds = Array.isArray(raw)
      ? (raw as any[])
          .filter(c => c && typeof c === 'object' && typeof c.名称 === 'string' && c.名称.trim() && typeof c.可用 === 'boolean')
          .map(c => ({ 名称: String(c.名称).trim(), 可用: Boolean(c.可用) }))
      : null
    return { 主体: (f.主体 as string) || '', 描写: (f.描写 as string) || '', 特殊指令: cmds && cmds.length ? cmds : null }
  }
  const s = String(f || '').trim()
  if (!DIR_RE.test(s) && s.includes('（')) {
    const i = s.indexOf('（')
    return { 主体: s.slice(0, i).trim(), 描写: s.slice(i + 1).replace(/）$/, '').trim(), 特殊指令: null }
  }
  return { 主体: s, 描写: '', 特殊指令: null }
}

type SetFn = (partial: Partial<GameState>) => void
type GetFn = () => GameState

/** 共享 SSE 流处理：send 与 sendHidden 复用。所有消息更新走不可变拷贝，
 *  使 React 能跳过未变消息（仅最后一条流式更新重渲）。 */
function runChatStream(msg: string, sid: string, get: GetFn, set: SetFn, hidden: boolean): Promise<void> {
  return new Promise<void>(resolve => {
    streamChat(msg, sid, {
      onSession: (id) => {
        set({ sessionId: id })
        sessionStorage.setItem(SID_KEY, id)
      },
      onDelta: (text) => {
        if (!text) return
        const messages = get().messages
        const last = messages[messages.length - 1]
        if (!last || last.role !== 'assistant' || !last.segs) return
        const segs = last.segs.slice()
        const lastSeg = segs[segs.length - 1]
        if (lastSeg && lastSeg.kind === 'text') {
          // 新建 text seg，避免 mutate
          segs[segs.length - 1] = { kind: 'text', text: lastSeg.text + text }
        } else {
          segs.push({ kind: 'text', text })
        }
        const newLast: ChatMessage = { ...last, segs }
        set({ messages: [...messages.slice(0, -1), newLast] })
      },
      onTool: (name, args) => {
        const messages = get().messages
        const last = messages[messages.length - 1]
        if (last && last.role === 'assistant' && last.segs) {
          const newLast: ChatMessage = { ...last, segs: [...last.segs, { kind: 'tool', name }] }
          set({ messages: [...messages.slice(0, -1), newLast] })
        }
        set({ turnTools: get().turnTools + 1 })
        get().waitAppend('推演中：' + name, args)
      },
      onState: (data) => {
        get().syncSlot(data)
        get().handleStateEvent(data)
        get().waitAppend('state: ' + (data.界面 || '?'), JSON.stringify(data, null, 2))
      },
      onError: (m) => {
        const messages = get().messages
        const last = messages[messages.length - 1]
        if (last && last.role === 'assistant' && last.segs) {
          const newLast: ChatMessage = { ...last, segs: [...last.segs, { kind: 'text', text: '[错误] ' + m }] }
          set({ messages: [...messages.slice(0, -1), newLast] })
        }
      },
      onDone: (_err, _result) => {
        const messages = get().messages
        const last = messages[messages.length - 1]
        if (last && last.role === 'assistant' && (!last.segs || !last.segs.length)) {
          const newLast: ChatMessage = { ...last, segs: [{ kind: 'text', text: '（无内容返回）' }] }
          set({ messages: [...messages.slice(0, -1), newLast] })
        }
        get().saveLog(get().pendingUser, last && last.role === 'assistant' ? cleanSegs(last.segs || []) : [])
        set({ pendingUser: null, steps: -1, busy: false })
        resolve()
      },
    })
  })
}

export const useGameStore = create<GameState>((set, get) => {
  setSlotRef(readSlot())

  return {
    sessionId: sessionStorage.getItem(SID_KEY) || '',
    busy: false,
    cardBusy: false,
    pendingUser: null,
    currentSlot: readSlot(),
    selectedMember: null,
    gateMode: false,
    gateSaves: [],
    gateSaveCnt: 0,
    gateLoading: false,
    lastExpl: null,
    party: null,
    headband: { region: '—', scene: '待 启 程', clock: '', icon: '◐', cal: '', saveRemain: null },
    stage: null,
    stageExpanded: false,
    prevSceneKey: null,
    lastStageSig: '',
    inBattle: false,
    lastBattle: null,
    lastParse: null,
    bPick: null,
    bEnded: false,
    displayState: {},
    lastOrder: [],
    lastPlayedRound: 0,
    battleSeq: 0,
    preFight: null,
    battleEnd: null,
    replayLock: false,
    replayChain: null,
    activeTab: 'travel',
    messages: [],
    steps: -1,
    turnTools: 0,
    modal: null,
    wizardOpen: false,
    toasts: [],
    waitLines: [],
    composerDraft: '',

    setSlot(v) {
      const n = parseInt(String(v), 10) || 0
      setSlotRef(n)
      set({ currentSlot: n })
      sessionStorage.setItem(SLOT_KEY, String(n))
    },

    syncSlot(d) {
      if (!d || typeof d !== 'object') return
      const st = get()
      if (d.删除槽位 !== undefined && parseInt(String(d.删除槽位), 10) === st.currentSlot) {
        get().setSlot(0)
        get().enterGate()
        return
      }
      if (d.槽位 !== undefined && parseInt(String(d.槽位), 10) !== st.currentSlot) {
        get().setSlot(d.槽位 as number)
        if (st.gateMode && st.currentSlot > 0) get().enterGame()
      }
    },

    enterGate() {
      set({ gateMode: true, activeTab: 'travel' })
      get().loadGateSaves()
    },

    enterGame() {
      set({ gateMode: false })
      get().refreshParty()
    },

    async loadGateSaves() {
      set({ gateLoading: true })
      const d = await fetchUi({ 类型: '开始游戏' })
      const saves = (d.存档列表 as any) || []
      set({ gateSaves: saves, gateSaveCnt: saves.length, gateLoading: false })
    },

    applyExplorationState(d) {
      if (!d || d.界面 !== 'exploration-ui') return
      const pos = (d.当前位置 as string) || ''
      const parts = pos.split('·')
      const region = parts.length > 1 ? parts[0] : '—'
      const sceneName = parts.length > 1 ? parts[1] : pos || '待 启 程'
      const saveRemain = d.剩余 == null ? null : `距自动存档 ${d.剩余} 轮`
      set({
        headband: {
          region,
          scene: sceneName,
          clock: (d.时段 as string) || '',
          icon: HB_ICON[d.时段 as string] || '◐',
          cal: (d.时间 as string) || '',
          saveRemain,
        },
      })
      get().renderParty(d)
      if (d.剧情描写 == null && !(d.场景要素 || []).length && !(d.相邻出口 || []).length) return
      const sig =
        (d.当前位置 || '') + '|' + (d.剧情描写 || '') + '|' + JSON.stringify(d.场景要素 || []) + '|' + JSON.stringify(d.相邻出口 || [])
      if (sig === get().lastStageSig) return
      const nar = (d.剧情描写 == null ? '' : String(d.剧情描写).replace(/\\n/g, '\n')).trim()
      const changes = ((d.结算 as any) || []).map((r: any) => r && r.变更).filter(Boolean)
      const els = ((d.场景要素 as any) || [])
        .map(normEl)
        .filter((f: any) => f.主体 && !DIR_RE.test(f.主体 + '（' + f.描写 + '）'))
      const exits = ((d.相邻出口 as any) || []).map((e: any) => ({ 方位: e.方位, 邻场景: e.邻场景 }))
      set({
        lastExpl: d,
        lastStageSig: sig,
        prevSceneKey: sceneName,
        stage: { narration: nar, changes, elements: els, exits, hasContent: !!(nar || changes.length) },
        stageExpanded: false,
      })
    },

    renderParty(d) {
      if (!d) {
        set({ party: null })
        return
      }
      set({
        party: {
          体力: d.体力 == null ? null : (d.体力 as number),
          金钱: d.金钱 == null ? null : (d.金钱 as number),
          队伍状态: (d.队伍状态 as MemberStatus[]) || [],
        },
      })
      // 选中态随队伍变化校正
      const names = ((d.队伍状态 as MemberStatus[]) || []).map(m => m.名称)
      const sel = get().selectedMember
      if (sel && !names.includes(sel)) set({ selectedMember: null })
    },

    async refreshParty() {
      if (get().inBattle) return
      if (!get().currentSlot) {
        get().renderParty(null)
        return
      }
      try {
        const d = await engineGo([{ 类型: '返回游戏' }])
        if (d && d.界面 === 'exploration-ui' && d.当前位置) {
          get().renderParty(d)
          get().applyExplorationState(d)
        } else {
          get().renderParty(null)
        }
      } catch {
        get().renderParty(null)
      }
    },

    composeExploration(d) {
      const lines: string[] = []
      lines.push((`### 【${(d.当前位置 || '').replace('·', ' · ')}】 ${d.时段 || ''} ${d.时间 || ''}`).trim(), '')
      if (d.剧情描写) lines.push(d.剧情描写 as string, '')
      for (const r of (d.结算 as any) || []) if (r && r.变更) lines.push('`' + r.变更 + '`')
      lines.push('')
      const els = (d.场景要素 as any) || []
      const exits = (d.相邻出口 as any) || []
      if (els.length || exits.length) {
        lines.push('周围情况')
        for (const e of els) lines.push('- ' + e)
        for (const e of exits) lines.push(`- ${e.方位}（通往${e.邻场景}）`)
        lines.push('')
      }
      const ms = ((d.队伍状态 as MemberStatus[]) || []).map(m => `- \`${m.名称}\` 气血(${m.气血}/${m.气血上限}) 内力(${m.内力}/${m.内力上限})`)
      if (ms.length) lines.push(`当前队伍 体力${d.体力 ?? '—'} 金钱${d.金钱}`, ...ms)
      return lines.join('\n')
    },

    addGmBlockText(text) {
      if (!text) return
      const msg: ChatMessage = { role: 'assistant', segs: [{ kind: 'text', text }] }
      const messages = [...get().messages, msg]
      set({ messages })
      persistLog(messages)
    },

    setSteps(idx) {
      if (idx > 0) {
        // 与原版一致：每次点亮先清空等待日志，避免多次 setSteps(1) 累积重复行
        set({ steps: idx, turnTools: 0, waitLines: [] })
        get().waitAppend('— 等待 GM 响应 —')
      } else {
        set({ steps: -1 })
      }
    },

    waitAppend(text, detail) {
      const line: WaitLine = { id: waitSeq++, summary: text, detail }
      set({ waitLines: [...get().waitLines, line] })
    },

    addSysLine(text, opts) {
      const o = opts || {}
      let toasts = get().toasts
      if (o.replace && o.cls) toasts = toasts.filter(t => t.cls !== o.cls)
      const id = toastSeq++
      toasts = [...toasts, { id, text, cls: o.cls }]
      set({ toasts })
      const ms = o.long ? 7000 : 2600
      setTimeout(() => get().removeToast(id), ms)
    },

    removeToast(id) {
      set({ toasts: get().toasts.filter(t => t.id !== id) })
    },

    openUiModal(kind, d) {
      set({ modal: { kind, data: d } })
      return true
    },

    closeUiModal() {
      set({ modal: null })
    },

    setActiveTab(t) {
      set({ activeTab: t })
    },

    setSelectedMember(n) {
      set({ selectedMember: n, activeTab: 'char' })
    },

    openWizard() {
      set({ wizardOpen: true })
    },

    closeWizard() {
      set({ wizardOpen: false })
    },

    setBPick(p) {
      set({ bPick: p })
    },

    setComposerDraft(v) {
      set({ composerDraft: v })
    },

    enterBattle(d) {
      const first = !get().inBattle
      set({ inBattle: true, preFight: null })
      if (first) {
        set({ bEnded: false, lastParse: null, lastPlayedRound: 0, displayState: {}, bPick: null, lastOrder: [], battleEnd: null, replayChain: null })
      }
      const st = d.战局状态 || {}
      if (Array.isArray(d.行动预告) && d.行动预告.length) set({ lastOrder: d.行动预告 as string[] })
      let parse: ParsedAction | null = null
      if (d.行动信息) parse = parseActionInfo(d.行动信息 as any)
      else if (d.玩家界面) parse = parsePlayerUI(d.玩家界面 as string)
      // 重建 displayState 基准
      const ds: Record<string, DisplayState> = { ...get().displayState }
      if (parse && parse.table) {
        for (const nm in parse.table) {
          const t = parse.table[nm]
          if (t.气血 && /\//.test(t.气血)) {
            const pr = t.气血.split('/')
            ds[nm] = ds[nm] || { hp: 0, mp: 0, maxhp: 1, maxmp: 1 }
            ds[nm].hp = +pr[0] || 0
            ds[nm].maxhp = +pr[1] || 1
          }
          if (t.内力 && /\//.test(t.内力)) {
            const pr = t.内力.split('/')
            ds[nm] = ds[nm] || { hp: 0, mp: 0, maxhp: 1, maxmp: 1 }
            ds[nm].mp = +pr[0] || 0
            ds[nm].maxmp = +pr[1] || 1
          }
        }
      }
      set({ lastBattle: d, lastParse: parse, displayState: ds, battleSeq: get().battleSeq + 1 })
      void st
    },

    exitBattle() {
      if (!get().inBattle) return
      set({ inBattle: false, lastParse: null, bPick: null, lastBattle: null, bEnded: false, preFight: null, battleEnd: null, replayLock: false, replayChain: null })
      get().setSteps(1)
    },

    setBattleDisplay(fn) {
      const ds = { ...get().displayState }
      fn(ds)
      set({ displayState: ds })
    },

    setBattleEnd(d) {
      set({ battleEnd: d, bEnded: !!d })
    },

    setReplayLock(v) {
      set({ replayLock: v })
    },

    setReplayChain(seq) {
      set({ replayChain: seq })
    },

    setLastPlayedRound(n) {
      set({ lastPlayedRound: Math.max(get().lastPlayedRound, n) })
    },

    async battleAct(action) {
      if (get().busy) { get().addSysLine('正在结算上一回合…'); return }
      set({ busy: true, replayLock: true })
      try {
        const d = await engineGo([action])
        if (d.错误) { get().addSysLine('战斗操控未成功：' + d.错误, { long: true }); return }
        if (d.界面 === 'battle-end-ui') {
          get().enterBattle(d)
        } else {
          const j = await engineJudge([{ 类型: '战斗-推进', 回合详情: d.回合详情 || [] }], { 当前剧情: '' })
          if (j.错误) { get().addSysLine('战斗推进打包未成功：' + j.错误, { long: true }); return }
          if (!(j.界面 === 'battle-ui' || j.界面 === 'battle-end-ui')) {
            get().addSysLine('战斗推进返回异常（无 battle 界面）——战场保留未动。', { long: true }); return
          }
          get().enterBattle(j)
          const rep = (j.战报 as string || '').trim()
          if (rep && /无法执行|未配置|内力不足|冷却|不存在/.test(rep.slice(0, 120))) {
            get().addSysLine('本回合未推进：' + rep.split('\n')[0].slice(0, 80), { long: true })
          }
        }
      } catch (e) {
        if (typeof e !== 'string') get().addSysLine('战斗调用失败：' + String(e))
      } finally {
        set({ busy: false })
      }
    },

    pickBattleTarget(kind, obj) {
      if (get().busy) { get().addSysLine('正在结算上一回合…'); return }
      if (kind === 'skill' && obj.范围 === '敌方全体') {
        void get().battleAct({ 类型: '战斗-使用武学', 武学: obj.名称 })
        return
      }
      const dir = kind === 'skill' ? (/^我方/.test(obj.范围 || '') ? '我方' : '敌方') : (obj.方向 === '对我方' ? '我方' : '敌方')
      const noSelf = kind === 'skill' && obj.范围 === '我方单体除自身'
      set({ bPick: { kind, name: obj.名称, dir, noSelf } })
    },

    resolveBattleAction(target) {
      const p = get().bPick
      if (!p) return
      set({ bPick: null })
      const action: Action = p.kind === 'skill'
        ? { 类型: '战斗-使用武学', 武学: p.name, 目标: target }
        : { 类型: '战斗-使用物品', 物品: p.name, 目标: target }
      void get().battleAct(action)
    },

    async startBattle(d, ctrl) {
      set({ preFight: null, busy: true, inBattle: true })
      try {
        const j = await engineJudge(
          [{ 类型: '战斗-开始', 我方: d.我方, 敌方: d.敌方, 允许逃跑: d.允许逃跑, 操控方式: ctrl }],
          { 当前剧情: `${(d.我方 || []).join('、')}与${(d.敌方 || []).join('、')}短兵相接，战局一触即发。` },
        )
        if (j.错误) { get().addSysLine('开战失败：' + j.错误, { long: true }); set({ inBattle: false, busy: false }); return }
        if (!(j.界面 === 'battle-ui' || j.界面 === 'battle-end-ui')) {
          get().addSysLine('开战返回异常（无 battle 界面）——战场保留未动。', { long: true }); set({ inBattle: false, busy: false }); return
        }
        get().enterBattle(j)
      } catch (e) {
        get().addSysLine('开战调用失败：' + String(e)); set({ inBattle: false })
      } finally {
        set({ busy: false })
      }
    },

    routeUi(d, ctx) {
      if (!d || typeof d !== 'object') return false
      get().syncSlot(d)
      ctx = ctx || {}
      switch (d.界面) {
        case 'battle-ui':
        case 'battle-end-ui':
          get().enterBattle(d)
          return true
        case 'exploration-battle-ui':
          set({ preFight: d })
          if (d.剧情描写 || d.场景要素) {
            get().applyExplorationState(Object.assign({}, d, { 界面: 'exploration-ui' }))
          }
          return true
        case 'exploration-ui':
          if (get().inBattle) get().exitBattle()
          get().applyExplorationState(d)
          if (ctx.showExpl) get().addGmBlockText((d.界面渲染 as string) || get().composeExploration(d))
          return true
        case 'message-ui':
          if (d.提示) get().addSysLine(d.提示 as string, { long: true, cls: 'warn', replace: true })
          return true
        case 'trade-buy-ui':
        case 'trade-sell-ui':
        case 'travel-ui':
        case 'inn-ui':
          return get().openUiModal(d.界面 as UiModalKind, d)
        default:
          return false
      }
    },

    handleStateEvent(d) {
      get().routeUi(d, { from: 'sse' })
    },

    async uiOp(action, opts) {
      opts = opts || {}
      if (get().cardBusy) return null
      if (opts.confirm && !confirm(opts.confirm)) return null
      set({ cardBusy: true })
      try {
        let d: EngineResult
        try {
          d = await engineGo([action], opts.slot)
        } catch (e) {
          get().addSysLine('调用失败：' + String(e))
          return null
        }
        const fails = ((d.结算 as any) || []).filter((r: any) => r && r.ok === false)
        if (d.错误 || fails.length) {
          get().addSysLine('操作未成功：' + (d.错误 || fails.map((r: any) => r.msg).join('；')))
        }
        if (!d.界面 && !d.错误) {
          get().addSysLine('该动作 go 未返回界面，按规则须走 judge 推演，面板不提供此入口——请到游历流用自然语言下达该指令（由 GM 结算）。')
        }
        get().routeUi(d, { from: 'tab', showExpl: opts.showExpl })
        if (opts.refresh) {
          try {
            await opts.refresh()
          } catch {
            /* ignore */
          }
        }
        return d
      } finally {
        set({ cardBusy: false })
      }
    },

    async elemCmdGo(cmd, subject, merchant) {
      let action: Action | null = null
      if (cmd === '购买') action = { 类型: '购买', 卖家: subject, 商人: merchant }
      else if (cmd === '出售') action = { 类型: '出售', 买家: subject, 商人: merchant }
      else if (cmd === '远行（舟车）') action = { 类型: '远行（舟车）' }
      else if (cmd === '休息' || cmd === '投宿') action = { 类型: '休息', 免费: false }
      else return
      try {
        const d = await engineGo([action])
        const fails = ((d.结算 as any) || []).filter((r: any) => r && r.ok === false)
        if (d.错误 || fails.length) {
          get().addSysLine('操作未成功：' + (d.错误 || fails.map((r: any) => r.msg).join('；')))
          return
        }
        if (get().routeUi(d, { from: 'elemcmd' })) return
        get().notifyGmJudge(action, d)
      } catch (e) {
        get().addSysLine('调用失败：' + String(e))
      }
    },

    async uiModalGo(action) {
      try {
        const d = await engineGo([action])
        const fails = ((d.结算 as any) || []).filter((r: any) => r && r.ok === false)
        if (d.错误 || fails.length) {
          get().addSysLine('操作未成功：' + (d.错误 || fails.map((r: any) => r.msg).join('；')))
          return
        }
        const routed = get().routeUi(d, { from: 'modal' })
        if (routed) {
          get().closeUiModal()
          return
        }
        if (d.界面) {
          get().closeUiModal()
          return
        }
        get().closeUiModal()
        get().notifyGmJudge(action, d)
      } catch (e) {
        get().addSysLine('调用失败：' + String(e))
      }
    },

    notifyGmJudge(action, d) {
      const t = (action && (action.类型 as string)) || ''
      let intent: string
      if (t === '远行（舟车）') intent = `远行前往${action.目的地 || '目的地'}`
      else if (t === '休息') intent = `休息（${action.等级 || ''}，${action.时长 || ''}刻${action.免费 ? '，免费' : ''}）`
      else if (t === '攻击') intent = '发起攻击'
      else if (t === '交谈观察') intent = '交谈观察'
      else intent = t || '行动'
      const pos = (d.当前位置 as string) || ''
      const lines = [
        `【系统：前端已直调 engine go 结算】玩家执行「${intent}」，engine go 已结算落盘（不要再调 go，直接调 engine judge）。`,
        `go 返回状态：当前位置 ${pos || '—'}，时辰 ${d.时间 || '—'}，体力 ${d.体力 != null ? d.体力 : '—'}。`,
        `请据此下调 engine judge（顶层 当前剧情/场景要素/经历概括，槽位用 ${get().currentSlot}），写本回合剧情并落盘，渲染 exploration-ui。`,
      ]
      get().send(lines.join('\n'), { hidden: true })
    },

    async send(msg, opts) {
      opts = opts || {}
      msg = (msg != null ? msg : '').trim()
      if (!msg || get().busy) return
      set({ busy: true, pendingUser: opts.hidden ? null : msg })
      const sid = get().sessionId
      if (!opts.hidden) {
        set({ messages: [...get().messages, { role: 'user', text: msg }] })
      }
      // 空 assistant 气泡
      set({ messages: [...get().messages, { role: 'assistant', segs: [] } as ChatMessage] })
      get().setSteps(1)

      await runChatStream(msg!, sid, get, set, !!opts.hidden)
    },

    sendHidden(msg) {
      // 仿原版 sendHidden：不经过 send()，不受 busy 拦截，自带灯链 + 聊天锁。
      // 注意不要重复 setSteps（调用方 exitBattle 等已点亮），此处只发流并管理收尾。
      const sid = get().sessionId
      set({ busy: true })
      // 空 assistant 气泡（隐藏指令不显示用户气泡）
      set({ messages: [...get().messages, { role: 'assistant', segs: [] } as ChatMessage] })
      void runChatStream(msg, sid, get, set, true)
    },

    sendLoadArchive(slot, target, label) {
      const directive =
        `用户正在 wuxia-rpg 游戏中，请加载 skill wuxia-rpg。\n` +
        `【读档指令】请以 engine go（槽位 ${slot}）执行 加载存档，目标："${target}"（存档名："${label}"）。\n` +
        `加载成功后 engine 返回 exploration-ui（含当前剧情/场景要素/队伍状态/经历概括），\n` +
        `请据此接续游戏会话——后续玩家输入按该存档状态执行。`
      get().setSlot(slot)
      set({ gateMode: false, activeTab: 'travel' })
      get().setSteps(1)
      get().send(directive, { hidden: true })
    },

    saveLog(userText, segs) {
      try {
        const log: ChatMessage[] = JSON.parse(sessionStorage.getItem(LOG_KEY) || '[]')
        if (userText != null) log.push({ role: 'user', text: userText })
        log.push({ role: 'assistant', segs })
        sessionStorage.setItem(LOG_KEY, JSON.stringify(log))
      } catch {
        /* ignore */
      }
    },

    loadLog() {
      let log: ChatMessage[]
      try {
        log = JSON.parse(sessionStorage.getItem(LOG_KEY) || '[]')
      } catch {
        log = []
      }
      set({ messages: log })
    },

    boot() {
      get().loadLog()
      let pendingBattle: EngineResult | null = null
      try {
        const pb = sessionStorage.getItem(PENDING_BATTLE)
        if (pb) {
          sessionStorage.removeItem(PENDING_BATTLE)
          pendingBattle = JSON.parse(pb)
        }
      } catch {
        /* ignore */
      }
      if (pendingBattle) {
        // 暂存战斗：跳过 enterGame 的 refreshParty
        get().routeUi(pendingBattle)
      } else if (get().currentSlot > 0) {
        get().enterGame()
      } else {
        get().enterGate()
      }
    },
  }
})

// 供组件按名取 roster 解析
export { rosterParse }
