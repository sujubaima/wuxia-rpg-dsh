// 战斗结构化数据解析，移植自 game-battle.js 的 parseActionInfo/parsePlayerUI/rosterParse。
import type { ActionInfo, ParsedAction, ParsedItem, ParsedRow, ParsedSkill } from '../types'

export function rosterParse(arr: string[] | undefined): { name: string; tag: string }[] {
  return (arr || []).map(s => {
    const i = String(s).indexOf('：')
    return i >= 0 ? { name: String(s).slice(0, i).trim(), tag: String(s).slice(i + 1).trim() } : { name: String(s).trim(), tag: '' }
  })
}

/** 解析 WEB_UI 结构化「行动信息」，构建与 parsePlayerUI 同形的 R。 */
export function parseActionInfo(ai: ActionInfo | undefined): ParsedAction {
  const R: ParsedAction = { actor: null, order: [], table: {}, skills: [], items: [] }
  if (!ai || typeof ai !== 'object') return R
  R.actor = ai.行动者 || null
  R.order = Array.isArray(ai.行动顺序) ? ai.行动顺序.slice() : []
  for (const c of ai.状态表 || []) {
    const hp = c.气血
    const mp = c.内力
    R.table[c.名称 || ''] = {
      阵营: c.阵营,
      名称: c.名称,
      气血: hp && typeof hp === 'object' ? `${hp.当前}/${hp.上限}` : '',
      内力: mp && typeof mp === 'object' ? `${mp.当前}/${mp.上限}` : '',
      状态: c.败阵 ? '败阵' : c.逃走 ? '逃走' : Array.isArray(c.状态) ? c.状态.join('、') : '无',
      冷却: Array.isArray(c.冷却) ? c.冷却.join('、') : '无',
      败阵: !!c.败阵,
      逃走: !!c.逃走,
    }
  }
  for (const s of ai.可用武学 || []) {
    R.skills.push({
      名称: s.名称 || '',
      类型: s.类型 || '',
      范围: s.范围 || '敌方单体',
      威力: s.威力 ?? '',
      内力: s.内力 ?? '',
      冷却: s.冷却 ?? '无冷却',
      可用: !!s.可用,
      冷却中: !!s.冷却中,
      冷却剩余: s.冷却剩余 || 0,
      内力不足: !!s.内力不足,
      武器不符: !!s.武器不符,
      特效: s.特效 || '',
    })
  }
  for (const it of ai.可用物品 || []) {
    R.items.push({ 名称: it.名称 || '', 数量: it.数量 || 0, 效果: it.效果 || '', 方向: it.方向 || '' })
  }
  return R
}

/** 解析旧版「玩家界面」文本表格，构建 R。 */
export function parsePlayerUI(txt: string | undefined): ParsedAction {
  const R: ParsedAction = { actor: null, order: [], table: {}, skills: [], items: [] }
  if (!txt) return R
  let mode = ''
  for (const ln of String(txt).split('\n')) {
    const mAct = ln.match(/行动角色：(.+)$/)
    if (mAct) R.actor = mAct[1].trim()
    if (/^\s*\|.*\|\s*$/.test(ln)) {
      if (ln.includes('名称') || /^[\s|:-]+$/.test(ln)) continue
      const cells = ln.split('|').map(s => s.trim()).filter(s => s.length)
      if (cells.length >= 6) {
        const c: ParsedRow = { 阵营: cells[0], 名称: cells[1].replace(/`/g, ''), 气血: cells[2], 内力: cells[3], 状态: cells[4], 冷却: cells[5] }
        R.table[c.名称 || ''] = c
      } else if (cells.length === 3) {
        const c: ParsedRow = { 阵营: cells[0], 名称: cells[1].replace(/`/g, ''), 状态列: cells[2] }
        R.table[c.名称 || ''] = c
      }
      continue
    }
    const mOrd = ln.match(/行动预告：【(.+?)】→\s*(.+)$/)
    if (mOrd) R.order = mOrd[2].split('→').map(s => s.trim()).filter(Boolean)
    if (ln.startsWith('可用武学')) { mode = 'sk'; continue }
    if (ln.startsWith('可用物品')) { mode = 'it'; continue }
    if (ln.startsWith('请输入')) { mode = ''; continue }
    if (mode === 'sk') {
      const m = ln.match(/^- `(.+?)`（(.+?)）\s*——\s*(.+)$/)
      if (m) {
        const inner = m[2].split(' / ')
        const flags = m[3].split('，')
        const sk: ParsedSkill = {
          名称: m[1], 类型: inner[0] || '', 范围: inner[1] || '敌方单体',
          威力: (inner[2] || '').replace('威力', ''), 内力: (inner[3] || '').replace('内力', ''),
          冷却: inner[4] || '', flags, 可用: flags.length === 1 && flags[0] === '可用',
        }
        R.skills.push(sk)
        continue
      }
      if (ln.startsWith('　特效') && R.skills.length) { R.skills[R.skills.length - 1].特效 = ln.replace(/^　/, ''); continue }
    }
    if (mode === 'it') {
      const m = ln.match(/^- `(.+?)`\s*×\s*(\d+)/)
      if (m) { R.items.push({ 名称: m[1], 数量: +m[2] }); continue }
      const e = ln.match(/^　效果：(.+?)（(对我方|对敌方)）/)
      if (e && R.items.length) { R.items[R.items.length - 1].效果 = e[1]; R.items[R.items.length - 1].方向 = e[2]; continue }
    }
  }
  return R
}
