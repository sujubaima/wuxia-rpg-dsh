import { useState } from 'react'
import { useGameStore } from '../../store'
import { esc } from '../../lib/markdown'
import { Btn } from '../ui'
import type { EngineResult } from '../../types'

export function BattleEndDialog() {
  const d = useGameStore(s => s.battleEnd)
  const exitBattle = useGameStore(s => s.exitBattle)
  const sendHidden = useGameStore(s => s.sendHidden)
  const [picks, setPicks] = useState<Record<string, string>>({})

  if (!d) return null
  const stt = (d.战局状态?.状态 as string) || ''
  const win = /我方胜|敌方认输/.test(stt)
  const draw = /平局/.test(stt)

  const buildSummary = (decisions: { 角色: string; 决定: string }[] | null): string => {
    let s = '【战斗已结束'
    if (win && decisions) s += ' · 玩家处决裁定完成'
    s += '】战局状态=' + JSON.stringify(d.战局状态 || {}) +
      '；战果=' + JSON.stringify(d.战果 || '') +
      '；经验结算=' + JSON.stringify(d.经验结算 || '')
    if (decisions) s += '；玩家对败方的逐人处置=' + JSON.stringify(decisions)
    if (win && decisions) {
      s += '。请据此进行后续操作：按处决结果叙事终局后果（杀者经 死亡 条目落实、放者保留），分发经验，judge 战后处置（战斗-结束 体力-20/时间+8、战利品/关系度等一并），返回 exploration-ui。'
    } else {
      s += '。请按战斗规则：' + (win ? '判定处决与战后处置。' : 'GM 代敌方处置我方败方（据敌方立场/动机/关系度裁定生死或掠财/羞辱/俘虏等），') +
        '随后 judge 战后处置（含 战斗-结束 体力-20/时间+8）与后续剧情，返回 exploration-ui。'
    }
    return s
  }
  const confirmAndSend = (decisions: { 角色: string; 决定: string }[] | null) => {
    exitBattle()
    sendHidden(buildSummary(decisions))
  }

  const cands = (d.处决候选 as { 名称?: string }[]) || []
  const cardCls = 'endcard' + (win || draw ? '' : ' lose')

  return (
    <div id="bEndMask" className="bmask show">
      <div className={cardCls} id="bEndCard">
        {win ? (
          <>
            <div className="verdict">大 获 全 胜</div>
            <div className="vsub">胜方处置败方，逐人裁定（逃走者不得处决）{cands.length ? '' : '——敌方全员已逃走，无可处决对象。'}</div>
            {cands.map(c => (
              <div className="exe-row" key={c.名称}>
                <span className="en">{c.名称}</span>
                <span className="ec">倒地不起，气息尚存</span>
                <button className={'ebtn kill' + (picks[c.名称 || ''] === '杀' ? ' on' : '')}
                  onClick={() => setPicks(p => ({ ...p, [c.名称 || '']: '杀' }))}>杀</button>
                <button className={'ebtn spare' + (picks[c.名称 || ''] === '放' ? ' on' : '')}
                  onClick={() => setPicks(p => ({ ...p, [c.名称 || '']: '放' }))}>放</button>
              </div>
            ))}
            <button className="gobtn" disabled={cands.some(c => !picks[c.名称 || ''])}
              onClick={() => confirmAndSend(cands.map(c => ({ 角色: c.名称 || '', 决定: picks[c.名称 || ''] })))}>
              {cands.length ? '镌 定 裁 决' : '继 续 战 后 处 置'}
            </button>
          </>
        ) : (
          <>
            <div className="verdict">{draw ? '难 分 高 下' : '一 败 涂 地'}</div>
            <div className="vsub">战报落定（{esc(stt)}）。GM 将代敌方处置并接续战后剧情。</div>
            <button className="gobtn" onClick={() => confirmAndSend(null)}>确 认 战 果 · 静 候 处 置</button>
          </>
        )}
      </div>
    </div>
  )
}
