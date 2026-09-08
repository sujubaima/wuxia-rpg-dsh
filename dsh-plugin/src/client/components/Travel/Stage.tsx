import { useGameStore } from '../../store'
import { renderInline } from '../../lib/markdown'

const C_DIRS = [['西北', '北', '东北'], ['西', '', '东'], ['西南', '南', '东南']]

function Compass({ exits }: { exits: { 方位: string; 邻场景: string }[] }) {
  const lastExpl = useGameStore(s => s.lastExpl)
  const setDraft = useGameStore(s => s.setComposerDraft)
  const exitMap: Record<string, string> = {}
  for (const e of exits) if (e.方位) exitMap[e.方位] = e.邻场景
  const hereName = lastExpl?.当前位置 ? String(lastExpl.当前位置).split('·').pop() : ''
  const n = Object.keys(exitMap).length
  let delay = 0
  return (
    <div className="compass-wrap">
      <div className="compass">
        {C_DIRS.flat().map((dir, idx) => {
          if (dir === '') {
            return (
              <div className="ccell here" key={idx}>
                <span className="nm">◈ {hereName}</span>
              </div>
            )
          }
          const target = exitMap[dir]
          if (!target) {
            return (
              <div className="ccell fog" key={idx}>
                <span className="dir">{dir}</span>
                <span className="nm">未知</span>
              </div>
            )
          }
          // 出口格带 nfp 入场动画 + 递增延时（与原版 makeEnter 一致）
          const d = delay
          delay += 0.11
          return (
            <div
              className="ccell exit nfp"
              key={idx}
              style={{ animationDelay: (0.08 + d).toFixed(2) + 's' }}
              title="填入移动指令"
              onClick={() => setDraft('前往' + target)}
            >
              <span className="dir">{dir}</span>
              <span className="nm">{target}</span>
            </div>
          )
        })}
      </div>
      <div className="cnote" dangerouslySetInnerHTML={{ __html: `已开启出口 <b>${n}</b> 方；<br>点方位格即可填指令。` }} />
    </div>
  )
}

export function Stage() {
  const stage = useGameStore(s => s.stage)
  const stageExpanded = useGameStore(s => s.stageExpanded)
  const inBattle = useGameStore(s => s.inBattle)
  const lastExpl = useGameStore(s => s.lastExpl)
  const setDraft = useGameStore(s => s.setComposerDraft)
  const elemCmdGo = useGameStore(s => s.elemCmdGo)

  if (!stage) {
    return (
      <div id="stage"><div id="stageIn">
        <div className="stage-empty">江湖未启，落笔开篇。<br />与 GM 对话推进剧情后，此处呈现当前场景。</div>
      </div></div>
    )
  }

  const awaiting = stage.hasContent && !stageExpanded
  const merchant = lastExpl?.当前场景类型 === '店铺' || lastExpl?.当前场景类型 === '客栈'
  let delay = 0
  const enterStyle = (): React.CSSProperties => {
    const d = 0.08 + delay
    delay += 0.11
    return { animationDelay: d.toFixed(2) + 's' }
  }

  return (
    <div
      id="stage"
      className={awaiting ? 'awaiting-click' : ''}
      onClick={awaiting ? () => useGameStore.setState({ stageExpanded: true }) : undefined}
    >
      <div id="stageIn">
        {/* 叙事 */}
        {stage.narration && (
          <div className="narration">
            {stage.narration.split(/\n{2,}/).map(s => s.trim()).filter(Boolean).map((para, i) => (
              <p
                key={i}
                className="nfp"
                style={enterStyle()}
                dangerouslySetInnerHTML={{ __html: renderInline(para).replace(/\n/g, '<br>') }}
              />
            ))}
          </div>
        )}
        {/* 状态变更 */}
        {stage.changes.length > 0 && (
          <div className="changes">
            {stage.changes.map((v, i) => (
              <span
                key={i}
                className={'chg nfp' + (/体力-|气血-|内力-/.test(v) ? ' hurt' : '')}
                style={enterStyle()}
              >{v}</span>
            ))}
          </div>
        )}
        {awaiting && <div className="expand-hint">点击此处继续…</div>}
        {/* 展开后的要素 + 罗盘 */}
        {!awaiting && stage.hasContent && (stage.elements.length > 0 || stage.exits.length > 0) && (
          <>
            {stage.elements.length > 0 && <div className="sc-title nfp" style={enterStyle()}>周 围 情 况</div>}
            <div className="scrow">
              <div className="sc-col">
                {stage.elements.length > 0 && (
                  <div className="sc-list">
                    {stage.elements.map((f, i) => {
                      const label = f.描写 ? `${f.主体}（${f.描写}）` : f.主体
                      return (
                        <div
                          key={i}
                          className="sc-elem nfp"
                          style={enterStyle()}
                          title="填入对话指令"
                          onClick={() => setDraft('与' + f.主体 + '交谈')}
                        >
                          <span className="dot">◆</span>
                          <span dangerouslySetInnerHTML={{ __html: renderInline(label) }} />
                          {f.特殊指令 && (
                            <span className="sc-cmds">
                              {f.特殊指令.map(cmd => {
                                const labelMap: Record<string, string> = { '购买': '购买', '出售': '出售', '远行（舟车）': '远行', '休息': '休息', '投宿': '投宿' }
                                return (
                                  <button
                                    key={cmd.名称}
                                    className="sc-cmd"
                                    disabled={!cmd.可用}
                                    onClick={cmd.可用 ? (e => { e.stopPropagation(); elemCmdGo(cmd.名称, f.主体, merchant) }) : undefined}
                                  >{labelMap[cmd.名称] || cmd.名称}</button>
                                )
                              })}
                            </span>
                          )}
                        </div>
                      )
                    })}
                  </div>
                )}
              </div>
              <Compass exits={stage.exits} />
            </div>
          </>
        )}
      </div>
    </div>
  )
}
