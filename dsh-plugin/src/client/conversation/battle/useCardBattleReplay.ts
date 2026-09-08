import { useCallback, useEffect, useRef, useState } from 'react'
import type { BattleEntry, ParsedAction } from '../../types'
import {
  applyMarker, applyResource, applyStatusSnapshot, buildReplayCues,
  displayFromParse, replayStepDuration, seedDisplayForReplay,
} from './replay'
import type { FighterDisplay, FloatTone, ReplayCue } from './replay'

const MAX_REPLAY_ENTRIES = 20

type Timer = ReturnType<typeof setTimeout>
type AnimLike = { cancel?: () => void; onfinish?: (() => void) | null; oncancel?: (() => void) | null }

interface Runtime {
  timers: Set<Timer>
  animations: Set<AnimLike>
  nodes: Set<HTMLElement>
}

function runtimeCreate(): Runtime {
  return { timers: new Set(), animations: new Set(), nodes: new Set() }
}

function runtimeClear(runtime: Runtime): void {
  for (const timer of runtime.timers) clearTimeout(timer)
  runtime.timers.clear()
  for (const animation of runtime.animations) animation.cancel?.()
  runtime.animations.clear()
  for (const node of runtime.nodes) node.remove()
  runtime.nodes.clear()
}

function schedule(runtime: Runtime, delay: number, callback: () => void): void {
  const timer = setTimeout(() => {
    runtime.timers.delete(timer)
    callback()
  }, Math.max(0, delay))
  runtime.timers.add(timer)
}

function animate(
  runtime: Runtime,
  node: HTMLElement | undefined | null,
  keyframes: Record<string, unknown>[],
  options: Record<string, unknown>,
): void {
  if (!node) return
  const runner = (node as any).animate
  if (typeof runner !== 'function') return
  try {
    const animation = runner.call(node, keyframes, options) as AnimLike
    runtime.animations.add(animation)
    const done = () => runtime.animations.delete(animation)
    animation.onfinish = done
    animation.oncancel = done
  } catch {
    // Web Animations API 不可用时，数值和状态仍由 React state 正常推进。
  }
}

function transient(
  runtime: Runtime,
  parent: HTMLElement | undefined | null,
  text: string,
  styles: Partial<CSSStyleDeclaration>,
  keyframes: Record<string, unknown>[],
  duration: number,
): void {
  if (!parent || !parent.ownerDocument) return
  const node = parent.ownerDocument.createElement('span')
  node.textContent = text
  Object.assign(node.style, styles)
  parent.appendChild(node)
  runtime.nodes.add(node)
  const remove = () => {
    runtime.nodes.delete(node)
    node.remove()
  }
  const runner = (node as any).animate
  if (typeof runner === 'function') {
    try {
      const animation = runner.call(node, keyframes, { duration, easing: 'ease-out', fill: 'forwards' }) as AnimLike
      runtime.animations.add(animation)
      const done = () => {
        runtime.animations.delete(animation)
        remove()
      }
      animation.onfinish = done
      animation.oncancel = done
      schedule(runtime, duration + 80, remove)
      return
    } catch {
      // fall through to timer-only cleanup
    }
  }
  schedule(runtime, duration, remove)
}

function floatColor(tone: FloatTone): string {
  switch (tone) {
    case 'damage': return '#e06a55'
    case 'critical': return '#f0b03a'
    case 'heal': return '#8ac86a'
    case 'mp-loss':
    case 'mp-gain': return '#5aa6e0'
    case 'miss': return '#9aa8c8'
    case 'buff': return '#d3ad58'
    case 'expire': return '#a8a09a'
  }
}

function showFloat(runtime: Runtime, card: HTMLElement | undefined, text: string, tone: FloatTone, duration: number): void {
  const status = tone === 'buff' || tone === 'expire'
  transient(runtime, card, text, status ? {
    position: 'absolute', left: 'auto', right: '-6px', top: '50%', zIndex: '25',
    color: floatColor(tone), fontSize: '12px', fontWeight: '700', whiteSpace: 'nowrap',
    pointerEvents: 'none', textShadow: '0 2px 6px rgba(0,0,0,.75)',
  } : {
    position: 'absolute', left: '50%', top: '-6px', zIndex: '25',
    color: floatColor(tone), fontSize: tone === 'critical' ? '23px' : tone === 'miss' ? '14px' : '19px',
    fontWeight: '700', whiteSpace: 'nowrap', pointerEvents: 'none',
    textShadow: '0 2px 6px rgba(0,0,0,.75)',
  }, status ? [
    { opacity: 0, transform: 'translate(8px,-50%)' },
    { opacity: 1, transform: 'translate(0,-50%)', offset: 0.18 },
    { opacity: 1, transform: 'translate(0,-50%)', offset: 0.78 },
    { opacity: 0, transform: 'translate(20px,-50%)' },
  ] : [
    { opacity: 0, transform: 'translate(-50%,6px)' },
    { opacity: 1, transform: 'translate(-50%,-3px)', offset: 0.18 },
    { opacity: 1, transform: 'translate(-50%,-18px)', offset: 0.72 },
    { opacity: 0, transform: 'translate(-50%,-34px)' },
  ], duration)
}

function showLabel(runtime: Runtime, card: HTMLElement | undefined, cue: Extract<ReplayCue, { kind: 'label' }>, duration: number): void {
  if (!card) return
  const enemy = card.dataset.side === 'enemy'
  let background = enemy
    ? 'linear-gradient(180deg,#e08a6a,#c56a50)'
    : 'linear-gradient(180deg,#d8b466,#b8923c)'
  let color = enemy ? '#f7ead6' : '#1a1208'
  if (cue.tone === 'item') {
    background = 'linear-gradient(180deg,#7a9a5a,#5a7a40)'
    color = '#f2f6ea'
  } else if (cue.tone === 'walk') {
    background = 'linear-gradient(180deg,#9aa8c8,#6a7aa0)'
    color = '#f2f6ea'
  }
  transient(runtime, card, cue.text, {
    position: 'absolute', left: '50%', top: '-30px', zIndex: '30', maxWidth: '280px',
    padding: '3px 11px', borderRadius: '9px', overflow: 'hidden', textOverflow: 'ellipsis',
    background, color, boxShadow: '0 2px 10px rgba(0,0,0,.55)', fontSize: '12px',
    whiteSpace: 'nowrap', pointerEvents: 'none',
  }, [
    { opacity: 0, transform: 'translate(-50%,8px)' },
    { opacity: 1, transform: 'translate(-50%,0)', offset: 0.16 },
    { opacity: 1, transform: 'translate(-50%,0)', offset: 0.78 },
    { opacity: 0, transform: 'translate(-50%,-12px)' },
  ], duration)
}

function showProjectile(
  runtime: Runtime,
  root: HTMLElement | null,
  overlay: HTMLElement | null,
  from: HTMLElement | undefined,
  to: HTMLElement | undefined,
  duration: number,
): void {
  if (!root || !overlay || !from || !to || !overlay.ownerDocument) return
  const rootBox = root.getBoundingClientRect()
  const fromBox = from.getBoundingClientRect()
  const toBox = to.getBoundingClientRect()
  const x0 = fromBox.left + fromBox.width / 2 - rootBox.left
  const y0 = fromBox.top + fromBox.height / 2 - rootBox.top
  const x1 = toBox.left + toBox.width / 2 - rootBox.left
  const y1 = toBox.top + toBox.height / 2 - rootBox.top
  const dx = x1 - x0
  const dy = y1 - y0
  const angle = Math.atan2(dy, dx) * 180 / Math.PI
  const node = overlay.ownerDocument.createElement('span')
  Object.assign(node.style, {
    position: 'absolute', left: `${x0}px`, top: `${y0}px`, zIndex: '35', width: '30px', height: '9px',
    marginLeft: '-15px', marginTop: '-4px', borderRadius: '5px', pointerEvents: 'none',
    background: from.dataset.side === 'enemy'
      ? 'linear-gradient(90deg,transparent,rgba(224,106,85,.4),#ff8a70)'
      : 'linear-gradient(90deg,transparent,rgba(200,164,86,.4),#f3d28a)',
    boxShadow: from.dataset.side === 'enemy'
      ? '0 0 10px 2px rgba(224,106,85,.8)'
      : '0 0 10px 2px rgba(200,164,86,.75)',
  } as Partial<CSSStyleDeclaration>)
  overlay.appendChild(node)
  runtime.nodes.add(node)
  const remove = () => {
    runtime.nodes.delete(node)
    node.remove()
  }
  const runner = (node as any).animate
  if (typeof runner === 'function') {
    try {
      const animation = runner.call(node, [
        { opacity: 0.4, transform: `translate(0,0) rotate(${angle}deg) scaleX(.5)` },
        { opacity: 1, transform: `translate(${dx}px,${dy}px) rotate(${angle}deg) scaleX(1)` },
      ], { duration, easing: 'cubic-bezier(.4,.1,.6,1)', fill: 'forwards' }) as AnimLike
      runtime.animations.add(animation)
      const done = () => {
        runtime.animations.delete(animation)
        remove()
      }
      animation.onfinish = done
      animation.oncancel = done
      schedule(runtime, duration + 80, remove)
      return
    } catch {
      // fall through
    }
  }
  schedule(runtime, duration, remove)
}

export function useCardBattleReplay(parse: ParsedAction, details: BattleEntry[]) {
  const [display, setDisplay] = useState<Record<string, FighterDisplay>>(
    () => seedDisplayForReplay(parse, details),
  )
  const [replayEntry, setReplayEntry] = useState<BattleEntry | null>(null)
  const [replayIndex, setReplayIndex] = useState(0)
  const [replayTotal, setReplayTotal] = useState(0)
  const [replaySkipped, setReplaySkipped] = useState(0)
  const [replaying, setReplaying] = useState(false)
  const lastPlayedRound = useRef(0)
  const rootRef = useRef<HTMLDivElement>(null)
  const overlayRef = useRef<HTMLDivElement>(null)
  const fighterRefs = useRef(new Map<string, HTMLButtonElement>())
  const runtimeRef = useRef(runtimeCreate())

  const registerFighter = useCallback((name: string, node: HTMLButtonElement | null) => {
    if (node) fighterRefs.current.set(name, node)
    else fighterRefs.current.delete(name)
  }, [])

  useEffect(() => {
    const runtime = runtimeRef.current
    runtimeClear(runtime)
    const fresh = details.filter(entry => Number(entry.回合 || 0) > lastPlayedRound.current)
    // 进入战斗 Card 后延迟 500ms 再开始回放或解锁玩家回合，
    // 避免一进场就立即开打，给玩家一个看清阵形的缓冲。
    if (!fresh.length) {
      const idle = setTimeout(() => {
        setDisplay(displayFromParse(parse))
        setReplayEntry(null)
        setReplayIndex(0)
        setReplayTotal(0)
        setReplaySkipped(0)
        setReplaying(false)
      }, 500)
      runtime.timers.add(idle)
      return () => {
        clearTimeout(idle)
        runtime.timers.delete(idle)
      }
    }

    const skipped = Math.max(0, fresh.length - MAX_REPLAY_ENTRIES)
    const queue = skipped ? fresh.slice(-MAX_REPLAY_ENTRIES) : fresh
    const maxRound = Math.max(lastPlayedRound.current, ...fresh.map(entry => Number(entry.回合 || 0)))
    const duration = replayStepDuration(queue.length)
    const scale = duration / 1900
    let cancelled = false
    let index = 0

    if (lastPlayedRound.current === 0) setDisplay(seedDisplayForReplay(parse, queue))
    setReplayTotal(queue.length)
    setReplaySkipped(skipped)
    setReplaying(true)

    const card = (name: string) => fighterRefs.current.get(name)
    const runCue = (cue: ReplayCue) => {
      if (cancelled) return
      if (cue.kind === 'label') {
        showLabel(runtime, card(cue.actor), cue, Math.max(620, duration * 0.78))
      } else if (cue.kind === 'lunge') {
        const node = card(cue.actor)
        const direction = node?.dataset.side === 'enemy' ? 32 : -32
        animate(runtime, node, [
          { transform: 'translateY(0) scale(1)' },
          { transform: `translateY(${direction}px) scale(1.07)`, offset: 0.34 },
          { transform: `translateY(${direction}px) scale(1.07)`, offset: 0.58 },
          { transform: 'translateY(0) scale(1)' },
        ], { duration: Math.max(430, duration * 0.52), easing: 'ease' })
      } else if (cue.kind === 'projectile') {
        showProjectile(runtime, rootRef.current, overlayRef.current, card(cue.actor), card(cue.target), Math.max(250, duration * 0.25))
      } else if (cue.kind === 'impact') {
        const node = card(cue.target)
        animate(runtime, node, [
          { transform: 'translateX(0)', boxShadow: '0 0 0 rgba(224,106,85,0)' },
          { transform: 'translateX(-9px) rotate(-1.3deg)', boxShadow: cue.critical ? '0 0 26px 5px rgba(240,176,58,.82)' : '0 0 22px 4px rgba(224,106,85,.72)', offset: 0.18 },
          { transform: 'translateX(7px)', offset: 0.34 },
          { transform: 'translateX(-5px) rotate(.9deg)', offset: 0.5 },
          { transform: 'translateX(4px)', offset: 0.66 },
          { transform: 'translateX(0)', boxShadow: '0 0 0 rgba(224,106,85,0)' },
        ], { duration: Math.max(420, duration * 0.45), easing: 'ease' })
      } else if (cue.kind === 'float') {
        showFloat(runtime, card(cue.target), cue.text, cue.tone, Math.max(620, duration * 0.72))
      } else if (cue.kind === 'resource') {
        setDisplay(current => applyResource(current, cue.target, cue.resource, cue.value))
      } else if (cue.kind === 'snapshot') {
        setDisplay(current => applyStatusSnapshot(current, cue.statuses))
      } else if (cue.kind === 'defeat') {
        setDisplay(current => applyMarker(current, cue.target, 'dead'))
      } else if (cue.kind === 'flee') {
        setDisplay(current => applyMarker(current, cue.target, 'fled'))
        showFloat(runtime, card(cue.target), '成功脱身', 'miss', Math.max(620, duration * 0.72))
      }
    }

    const next = () => {
      if (cancelled) return
      runtimeClear(runtime)
      if (index >= queue.length) {
        lastPlayedRound.current = maxRound
        setDisplay(displayFromParse(parse))
        setReplayEntry(null)
        setReplayIndex(0)
        setReplayTotal(0)
        setReplaying(false)
        return
      }
      const entry = queue[index]
      index += 1
      setReplayEntry(entry)
      setReplayIndex(index)
      for (const cue of buildReplayCues(entry)) {
        schedule(runtime, cue.at * scale, () => runCue(cue))
      }
      schedule(runtime, duration, next)
    }

    // 首次进入延迟 500ms 再开打（仅首条；后续回合由 duration 节奏驱动）
    const startDelay = setTimeout(() => next(), 500)
    runtime.timers.add(startDelay)
    return () => {
      cancelled = true
      clearTimeout(startDelay)
      runtime.timers.delete(startDelay)
      runtimeClear(runtime)
    }
  }, [details, parse])

  useEffect(() => () => runtimeClear(runtimeRef.current), [])

  return {
    display,
    replayEntry,
    replayIndex,
    replayTotal,
    replaySkipped,
    replaying,
    rootRef,
    overlayRef,
    registerFighter,
  }
}
