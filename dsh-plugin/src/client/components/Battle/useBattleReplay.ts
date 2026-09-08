import { useEffect, useRef } from 'react'
import { useGameStore } from '../../store'
import { cardRefs, getCard } from './battleRefs'
import { el } from './dom'
import { rosterParse } from '../../lib/battleParse'
import type { BattleEntry, EngineResult, HpChange } from '../../types'
// TargetSettle 仅作为 e.目标结算 元素类型，由 EngineResult 推断，无需显式引入

const scrollwait = (ms: number) => new Promise<void>(r => setTimeout(r, ms))

function clearActing() {
  cardRefs.forEach(c => c.classList.remove('acting'))
}

function lungeCard(card: HTMLDivElement | undefined) {
  if (!card) return
  const cls = card.classList.contains('enemy') ? 'lunge-down' : 'lunge-up'
  card.classList.remove('lunge-up', 'lunge-down')
  void card.offsetWidth
  card.classList.add(cls)
  setTimeout(() => card.classList.remove(cls), 950)
}
function shakeCard(card: HTMLDivElement | undefined, critFlash: boolean) {
  if (!card) return
  card.classList.remove('shake', 'hitflash')
  void card.offsetWidth
  card.classList.add('shake')
  if (critFlash) card.classList.add('hitflash')
  setTimeout(() => card.classList.remove('shake', 'hitflash'), 1050)
}
function flyProjectile(from: HTMLDivElement | undefined, to: HTMLDivElement | undefined) {
  if (!from || !to) return
  const a = from.getBoundingClientRect(), b = to.getBoundingClientRect()
  const x0 = a.left + a.width / 2, y0 = a.top + a.height / 2, x1 = b.left + b.width / 2, y1 = b.top + b.height / 2
  const p = document.createElement('div')
  p.className = 'proj' + (from.classList.contains('enemy') ? ' foe' : '')
  p.style.left = x0 + 'px'
  p.style.top = y0 + 'px'
  document.body.appendChild(p)
  const ang = (Math.atan2(y1 - y0, x1 - x0) * 180) / Math.PI
  const dx = x1 - x0, dy = y1 - y0
  const anim = p.animate(
    [
      { transform: `translate(0,0) rotate(${ang}deg)`, opacity: 0.85 },
      { transform: `translate(${dx}px,${dy}px) rotate(${ang}deg)`, opacity: 1 },
    ],
    { duration: 700, easing: 'cubic-bezier(.4,.1,.6,1)' },
  )
  anim.onfinish = () => p.remove()
}
function actionLabel(card: HTMLDivElement | undefined, text: string | null, cls?: string) {
  if (!card || !text) return
  const tag = document.createElement('div')
  tag.className = 'actlabel ' + (cls || '')
  tag.textContent = text
  card.appendChild(tag)
  setTimeout(() => tag.classList.add('out'), 1500)
  setTimeout(() => tag.remove(), 1780)
}
function floatCard(name: string, txt: string, cls: string) {
  const card = getCard(name)
  if (!card) return
  const f = el('div', 'float ' + cls, txt)
  card.appendChild(f)
  setTimeout(() => f.remove(), 1800)
}
function sfloat(who: string, txt: string, cls: string) {
  const card = getCard(who)
  if (!card) return
  const f = el('div', 'float sfloat ' + cls, txt)
  card.appendChild(f)
  setTimeout(() => f.remove(), 2000)
}

function setCardBar(name: string, which: 'hp' | 'mp', val: number) {
  const st = useGameStore.getState()
  const ds = st.displayState[name] || { hp: 0, mp: 0, maxhp: 1, maxmp: 1 }
  const max = which === 'hp' ? ds.maxhp : ds.maxmp
  if (!max) return
  // 更新 max 缓存（不触发重渲：Roster 不订阅 displayState）
  const next = { ...ds }
  if (which === 'hp') next.hp = val
  else next.mp = val
  st.setBattleDisplay(s => { s[name] = next })
  // 命令式改 DOM 条（与原版一致，避免 React 重渲打断动画）
  const card = getCard(name)
  if (!card) return
  const bar = card.querySelector('.bar.' + which) as HTMLDivElement | null
  if (!bar) return
  const i = bar.querySelector('i') as HTMLElement | null
  const span = bar.querySelector('span') as HTMLElement | null
  const p = Math.max(0, Math.min(100, (val / max) * 100))
  if (i) i.style.width = p + '%'
  if (span) span.textContent = (which === 'hp' ? '气血 ' : '内力 ') + val + '/' + max
  if (which === 'hp') bar.classList.toggle('low', p < 35)
}

function hpchg(who: string, v: HpChange | HpChange[] | undefined, crit?: boolean) {
  const ar = v ? (Array.isArray(v) ? v : [v]) : []
  for (const ch of ar) {
    if (ch.原值 == null || ch.新值 == null) continue
    const diff = ch.原值 - ch.新值
    setCardBar(who, 'hp', ch.新值)
    if (diff > 0) { floatCard(who, '-' + diff, crit ? 'crit' : 'dmg'); shakeCard(getCard(who), !!crit) }
    else if (diff < 0) floatCard(who, '+' + -diff, 'heal')
  }
}
function mpchg(who: string, v: HpChange | HpChange[] | undefined) {
  const ar = v ? (Array.isArray(v) ? v : [v]) : []
  for (const ch of ar) {
    if (ch.原值 == null || ch.新值 == null) continue
    const diff = ch.原值 - ch.新值
    setCardBar(who, 'mp', ch.新值)
    if (diff > 0) floatCard(who, '-' + diff, 'mpdmg')
    else if (diff < 0) floatCard(who, '+' + -diff, 'mpheal')
  }
}
function statusChg(applied: any[] | undefined | null, expired: any[] | undefined | null, actor: string) {
  for (const g of applied || []) sfloat(g.目标 || actor, '＋' + (g.名称 || ''), 'buff')
  for (const s of expired || []) sfloat(actor, '－' + (s.名称 || ''), 'expire')
}

const badgeKey = (txt: string) => {
  const m = /^(【[^】]+】)/.exec(txt)
  return m ? m[1] : txt
}
function applySnapshot(snap: Record<string, string[]> | undefined) {
  if (!snap) return
  for (const name in snap) {
    const card = getCard(name)
    if (!card) continue
    let sts = card.querySelector('.sts') as HTMLDivElement | null
    if (!sts) { sts = document.createElement('div'); sts.className = 'sts'; card.appendChild(sts) }
    const olds = [...sts.querySelectorAll('.stg:not(.cd)')] as HTMLElement[]
    const news = (snap[name] || []).slice()
    const usedOld = new Array(olds.length).fill(false)
    const kept: HTMLElement[] = []
    for (const txt of news) {
      const key = badgeKey(txt)
      const idx = olds.findIndex((g, i) => !usedOld[i] && badgeKey(g.textContent || '') === key)
      if (idx >= 0) { usedOld[idx] = true; olds[idx].textContent = txt; kept.push(olds[idx]) }
    }
    olds.forEach((g, i) => { if (!usedOld[i]) { g.style.animation = 'badgeOut .3s ease-in forwards'; setTimeout(() => g.remove(), 300) } })
    for (const txt of news) {
      const key = badgeKey(txt)
      if (!kept.some(g => g.textContent === txt)) {
        const g = document.createElement('span')
        g.className = 'stg'
        g.textContent = txt
        g.style.animation = 'badgeIn .4s ease-out'
        const firstCd = sts.querySelector('.stg.cd')
        if (firstCd) sts.insertBefore(g, firstCd)
        else sts.appendChild(g)
      }
    }
  }
}

function applyReplayEntry(e: BattleEntry) {
  clearActing()
  const aCard = getCard(e.行动者 || '')
  if (aCard) {
    aCard.classList.add('acting')
    lungeCard(aCard)
    const foeCls = aCard.classList.contains('enemy')
    let txt: string | null = null
    let cls = foeCls ? 'foe' : ''
    if (e.类型 === '武学') txt = '【' + (e.技能 || '?') + (e.招式 ? '·' + e.招式 : '') + '】' + (e.目标 ? ' → ' + e.目标 : '')
    else if (e.类型 === '物品') { txt = '用药【' + (e.物品 || '?') + '】' + (e.目标 ? ' → ' + e.目标 : ''); cls = 'item' }
    else if (e.类型 === '休息') { txt = '敛气调息'; cls = 'walk' }
    else if (e.类型 === '逃跑') { txt = '要遁走！'; cls = 'walk' }
    else if (e.类型 === '认输') { txt = '认输'; cls = 'walk' }
    else if (e.类型 === '运功') { txt = '运功凝神'; cls = 'walk' }
    actionLabel(aCard, txt, cls)
  }

  if (e.类型 === '武学') {
    if (e.闪避) {
      const tgt = getCard(e.目标 || '')
      if (e.目标结算) {
        e.目标结算.forEach((te, i) => {
          setTimeout(() => flyProjectile(aCard, getCard(te.目标 || '')), 600 + i * 120)
          setTimeout(() => { if (te.闪避) floatCard(te.目标 || '', '闪避', 'miss') }, 1350 + i * 120)
        })
      } else if (tgt) {
        setTimeout(() => flyProjectile(aCard, tgt), 600)
        setTimeout(() => floatCard(e.目标 || '', '闪避', 'miss'), 1350)
      } else floatCard(e.目标 || '', '闪避', 'miss')
    } else {
      const tgt = getCard(e.目标 || '')
      if (e.目标结算) {
        e.目标结算.forEach((te, i) => {
          setTimeout(() => flyProjectile(aCard, getCard(te.目标 || '')), 600 + i * 120)
          setTimeout(() => hpchg(te.目标 || '', te.目标气血变化), 1350 + i * 120)
          setTimeout(() => mpchg(te.目标 || '', te.目标内力变化), 1350 + i * 120)
          setTimeout(() => statusChg(te.施加状态, null, te.目标 || ''), 1350 + i * 120)
        })
      } else if (tgt) {
        setTimeout(() => flyProjectile(aCard, tgt), 600)
        setTimeout(() => hpchg(e.目标 || '', e.目标气血变化), 1350)
        setTimeout(() => mpchg(e.目标 || '', e.目标内力变化), 1350)
        setTimeout(() => statusChg(e.施加状态, null, e.目标 || ''), 1350)
      } else {
        hpchg(e.目标 || '', e.目标气血变化)
        mpchg(e.目标 || '', e.目标内力变化)
      }
      if (e.击败) setTimeout(() => { const t = getCard(e.目标 || ''); if (t) t.classList.add('dead') }, 1350)
    }
    if (e.行动者内力变化) setCardBar(e.行动者 || '', 'mp', e.行动者内力变化.新值 || 0)
    if (e.行动者气血变化) setCardBar(e.行动者 || '', 'hp', e.行动者气血变化.新值 || 0)
    statusChg(e.施加状态, e.状态失效, e.行动者 || '')
  } else if (e.类型 === '物品') {
    hpchg(e.目标 || '', e.目标气血变化)
    mpchg(e.目标 || '', e.目标内力变化)
    statusChg(e.施加状态, e.状态失效, e.行动者 || '')
  } else if (e.类型 === '休息') {
    if (e.内力变化) {
      const rec = (e.内力变化.新值 || 0) - (e.内力变化.原值 || 0)
      setCardBar(e.行动者 || '', 'mp', e.内力变化.新值 || 0)
      if (rec > 0) floatCard(e.行动者 || '', '+' + rec, 'mpheal')
    }
    if (e.气血变化) {
      const rec = (e.气血变化.新值 || 0) - (e.气血变化.原值 || 0)
      setCardBar(e.行动者 || '', 'hp', e.气血变化.新值 || 0)
      if (rec > 0) floatCard(e.行动者 || '', '+' + rec, 'heal')
    }
    statusChg(null, e.状态失效, e.行动者 || '')
  } else if (e.类型 === '逃跑') {
    if (e.逃跑成功) { const c = aCard; if (c) c.classList.add('dead', 'fled') }
    else floatCard(e.行动者 || '', '未脱身', 'miss')
  } else if (e.类型 === '认输') {
    floatCard(e.行动者 || '', '认输', 'miss')
  } else if (e.类型 === '运功') {
    for (const s of e.获得状态 || []) floatCard(e.行动者 || '', '运功·' + (s || ''), 'buff')
  }
  applySnapshot(e.状态快照)
}

function seedOpeningDisplay(details: BattleEntry[]) {
  const seen: Record<string, boolean> = {}
  const take = (who: string | undefined, chg: HpChange | undefined, which: 'hp' | 'mp') => {
    if (!who || !chg || chg.原值 == null) return
    const k = who + '|' + which
    if (seen[k]) return
    seen[k] = true
    setCardBar(who, which, chg.原值)
  }
  for (const e of details) {
    take(e.行动者, e.行动者内力变化, 'mp')
    take(e.行动者, e.行动者气血变化, 'hp')
    take(e.行动者, e.气血变化, 'hp')
    take(e.行动者, e.内力变化, 'mp')
    take(e.目标, e.目标气血变化 as HpChange, 'hp')
    take(e.目标, e.目标内力变化 as HpChange, 'mp')
    for (const te of e.目标结算 || []) {
      if (te.目标气血变化) take(te.目标, te.目标气血变化 as HpChange, 'hp')
      if (te.目标内力变化) take(te.目标, te.目标内力变化 as HpChange, 'mp')
    }
  }
  clearActing()
}

function isEnd(d: EngineResult): boolean {
  return d.界面 === 'battle-end-ui' || (!!d.战局状态?.状态 && d.战局状态.状态 !== '进行中')
}

export function useBattleReplay(): void {
  const battleSeq = useGameStore(s => s.battleSeq)
  const inBattle = useGameStore(s => s.inBattle)
  const timerRef = useRef<ReturnType<typeof setTimeout> | null>(null)

  useEffect(() => {
    if (!inBattle) return
    const st = useGameStore.getState()
    const d = st.lastBattle
    if (!d) return
    const details = (d.回合详情 as BattleEntry[]) || []
    const fresh = details.filter(e => (e.回合 || 0) > st.lastPlayedRound)
    const first = st.lastPlayedRound === 0

    const end = () => {
      st.setReplayLock(false)
      if (isEnd(d)) st.setBattleEnd(d)
    }

    if (fresh.length) {
      st.setReplayLock(true)
      let i = 0
      if (first) {
        seedOpeningDisplay(fresh)
        void scrollwait(700).then(runStep)
      } else {
        runStep()
      }
      function runStep() {
        if (i >= fresh.length) {
          timerRef.current = null
          useGameStore.getState().setLastPlayedRound(Math.max(...fresh.map(e => e.回合 || 0), useGameStore.getState().lastPlayedRound))
          // 回放结束：清空逐帧链，回归终态静态预告
          useGameStore.getState().setReplayChain(null)
          end()
          return
        }
        const e = fresh[i++]
        applyReplayEntry(e)
        // 逐帧更新行动预告链：剩余未播回合的行动者 + 终态行动预告（与原版 renderChainSeq 一致）
        const remain = fresh.slice(i).map(x => x.行动者 || '')
        useGameStore.getState().setReplayChain([...remain, ...useGameStore.getState().lastOrder])
        timerRef.current = setTimeout(runStep, 2400)
      }
    } else {
      if (details.length) useGameStore.getState().setLastPlayedRound(Math.max(...details.map(e => e.回合 || 0)))
      end()
    }

    return () => {
      if (timerRef.current) { clearTimeout(timerRef.current); timerRef.current = null }
    }
  }, [battleSeq, inBattle])
}

// 供 BattleChain 用的行动预告顺序辅助（与原 renderBattleChain 一致）
export function battleChainSeq(st: { lastParse: any; lastOrder: string[] }, battleState: any): string[] {
  const cur = st.lastParse?.actor || null
  const tail = st.lastOrder.length ? st.lastOrder.slice() : []
  let seq: string[] = []
  if (cur) seq.push(cur)
  for (let i = 0; i < tail.length; i++) {
    if (i === 0 && cur && tail[i] === cur) continue
    seq.push(tail[i])
  }
  if (!seq.length) {
    if (st.lastParse?.actor) seq.push(st.lastParse.actor)
    if (st.lastParse?.order) for (const n of st.lastParse.order) if (!seq.includes(n)) seq.push(n)
  }
  if (!seq.length) seq = rosterParse(battleState?.我方).concat(rosterParse(battleState?.敌方)).map(r => r.name)
  return seq
}
