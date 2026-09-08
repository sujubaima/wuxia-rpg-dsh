import { useGameStore } from '../../store'
import { fmtMoney } from '../../lib/format'
import { esc } from '../../lib/markdown'
import { Btn, UiTable } from '../ui'
import type { EngineResult, UiModalKind } from '../../types'

function esc2(s: unknown) { return esc(s == null ? '' : String(s)) }

function TradeBuy({ d }: { d: EngineResult }) {
  const uiModalGo = useGameStore(s => s.uiModalGo)
  const money = d.金钱 as number
  const items = (d.货架 as any[]) || []
  return items.length ? (
    <UiTable
      headers={['物品', '数量', '价格', '类型', '子类型', '品级', '']}
      rows={items.map((it, i) => {
        const buy = (
          <Btn key={i}
            disabled={money != null && it.价格 != null && parseInt(String(money), 10) < parseInt(String(it.价格), 10)}
            onClick={() => {
              const n = prompt(`购买 ${it.名称} 数量（默认1）：`, '1')
              const cnt = parseInt(n || '', 10)
              if (!cnt || cnt < 1) return
              void uiModalGo({ 类型: '购买', 卖家: d.卖家, 物品: it.名称, 数量: cnt, 商人: !!d.商人, 价格: it.价格, 买家: d.买家 } as any)
            }}
          >{money != null && it.价格 != null && parseInt(String(money), 10) < parseInt(String(it.价格), 10) ? '金钱不足' : '购买'}</Btn>
        )
        return [
          <span className="rt-name" key="n" dangerouslySetInnerHTML={{ __html: esc2(it.名称) }} />,
          '×' + (it.数量 ?? 1), fmtMoney(it.价格), esc2(it.类型), esc2(it.子类型) || '—', esc2(it.品名 || (it.品级 ?? '')), buy,
        ]
      })}
    />
  ) : <div className="ui-empty">{esc2(d.卖家)}暂无可售物品</div>
}

function TradeSell({ d }: { d: EngineResult }) {
  const uiModalGo = useGameStore(s => s.uiModalGo)
  const items = (d.可售物品 as any[]) || []
  return items.length ? (
    <UiTable
      headers={['物品', '数量', '估价', '类型', '子类型', '品级', '']}
      rows={items.map((it, i) => [
        <span className="rt-name" key="n" dangerouslySetInnerHTML={{ __html: esc2(it.名称) }} />,
        '×' + (it.数量 ?? 1), fmtMoney(it.价格), esc2(it.类型), esc2(it.子类型) || '—', esc2(it.品名 || (it.品级 ?? '')),
        <Btn key={i} onClick={() => {
          const n = prompt(`出售 ${it.名称} 数量（默认1）：`, '1')
          const cnt = parseInt(n || '', 10)
          if (!cnt || cnt < 1) return
          void uiModalGo({ 类型: '出售', 买家: d.买家, 物品: it.名称, 数量: cnt, 商人: !!d.商人, 价格: it.价格, 卖家: d.卖家 } as any)
        }}>出售</Btn>,
      ])}
    />
  ) : <div className="ui-empty">无可售物品</div>
}

function TravelModal({ d }: { d: EngineResult }) {
  const uiModalGo = useGameStore(s => s.uiModalGo)
  const routes = (d.路线 as any[]) || []
  return routes.length ? (
    <UiTable
      headers={['目的地', '耗时', '费用', '']}
      rows={routes.map((r, i) => [
        <span className="rt-name" key="n" dangerouslySetInnerHTML={{ __html: esc2(r.目的地) }} />,
        `${r.耗时}天`, fmtMoney(r.费用),
        <Btn key={i} onClick={() => void uiModalGo({ 类型: '远行（舟车）', 目的地: r.目的地 }, { confirm: `启程前往 ${r.目的地}？耗时${r.耗时}天，费 ${fmtMoney(r.费用)}。` })}>前往</Btn>,
      ])}
    />
  ) : <div className="ui-empty">此驿站暂无直达路线，需经他处换乘</div>
}

function Inn({ d }: { d: EngineResult }) {
  const uiModalGo = useGameStore(s => s.uiModalGo)
  const money = d.金钱 as number
  const pct: Record<string, string> = { '0.15': '上限15%', '0.2': '上限20%', '0.25': '上限25%' }
  const levels = (d.等级 as any[]) || []
  return (
    <>
      {levels.length ? (
        <UiTable
          headers={['等级', '每刻单价', '体力/时辰', '气血内力/时辰', '费用(32刻)', '']}
          rows={levels.map((r, i) => {
            const fee = (r.每刻单价 || 0) * (r.时长 || 32)
            const poor = money != null && fee > 0 && parseInt(String(money), 10) < fee
            return [
              <span className="rt-name" key="n" dangerouslySetInnerHTML={{ __html: esc2(r.等级) }} />,
              `${r.每刻单价 || 0}钱/刻`, `${r.体力每时辰 || 0}/时辰`,
              esc2(pct[String(r.气血内力比例)] || ('上限' + (r.气血内力比例 || 0))), fmtMoney(fee),
              <Btn key={i} disabled={poor}
                onClick={() => void uiModalGo({ 类型: '休息', 等级: r.等级, 时长: r.时长 || 32, 免费: false }, { confirm: `休息（${r.等级}）4时辰？费 ${fmtMoney(fee)}，恢复体力/气血内力。` })}
              >{poor ? '金钱不足' : '休息'}</Btn>,
            ]
          })}
        />
      ) : <div className="ui-empty">无可休息等级</div>}
      <div className="ui-foot">休息结算后由 GM 承接休息剧情。差等级（露宿）不经此界面。</div>
    </>
  )
}

const BUILDERS: Record<UiModalKind, (d: EngineResult) => React.ReactNode> = {
  'trade-buy-ui': d => <TradeBuy d={d} />,
  'trade-sell-ui': d => <TradeSell d={d} />,
  'travel-ui': d => <TravelModal d={d} />,
  'inn-ui': d => <Inn d={d} />,
}

const TITLES: Record<UiModalKind, (d: EngineResult) => { title: string; sub?: string }> = {
  'trade-buy-ui': d => ({ title: `购买 · ${esc2(d.卖家)}${d.商人 ? ' （商人）' : ''}`, sub: `金钱 ${fmtMoney(d.金钱)}` }),
  'trade-sell-ui': d => ({ title: `出售 · ${esc2(d.买家)}${d.商人 ? ' （商人）' : ''}`, sub: `金钱 ${fmtMoney(d.金钱)}` }),
  'travel-ui': d => ({ title: `驿站 · ${esc2(d.当前区域)}`, sub: esc2(d.驿站类型) }),
  'inn-ui': d => ({ title: `客栈 · ${esc2(d.场景)}`, sub: `金钱 ${fmtMoney(d.金钱)}（固定4时辰/32刻）` }),
}

export function UiModal() {
  const modal = useGameStore(s => s.modal)
  const close = useGameStore(s => s.closeUiModal)
  if (!modal) return null
  const { title, sub } = TITLES[modal.kind](modal.data)
  return (
    <div id="modUi" className="show" onClick={e => { if (e.target === e.currentTarget) close() }}>
      <div className="ui-card">
        <div className="ui-head">
          <h3 dangerouslySetInnerHTML={{ __html: title + (sub ? ` <span class="ui-sub">${esc2(sub)}</span>` : '') }} />
          <button className="uibtn ui-close" title="返回游历" onClick={close}>×</button>
        </div>
        <div id="modUiBody">{BUILDERS[modal.kind](modal.data)}</div>
      </div>
    </div>
  )
}
