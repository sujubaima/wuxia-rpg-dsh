import { useEffect, useState } from 'react'
import { fmtMoney } from '../../lib/format'
import {
  EmptyState, LoadingState, PanelButton, PanelNotice, PanelTable, selectStyle,
} from '../panels/PanelPrimitives'

export type CardInteractionKind = 'buy' | 'sell' | 'travel' | 'inn'

function finiteNumber(value: unknown): number | null {
  if (value == null || value === '') return null
  const number = typeof value === 'number' ? value : Number(value)
  return Number.isFinite(number) ? number : null
}

function positiveCount(value: string, maximum: number): number | null {
  const count = Number(value)
  if (!Number.isInteger(count) || count < 1 || count > maximum) return null
  return count
}

function itemKey(item: any, index: number): string {
  return `${String(item?.名称 || '')}:${index}`
}

function itemGrade(item: any): string {
  return String(item?.品名 || item?.品级 || '—')
}

function titleOf(kind: CardInteractionKind, data: any): { title: string; sub: string } {
  switch (kind) {
    case 'buy':
      return {
        title: `购买 · ${String(data?.卖家 || '卖家')}${data?.商人 ? '（商人）' : ''}`,
        sub: `金钱 ${fmtMoney(data?.金钱)}`,
      }
    case 'sell':
      return {
        title: `出售 · ${String(data?.买家 || '收购方')}${data?.商人 ? '（商人）' : ''}`,
        sub: `金钱 ${fmtMoney(data?.金钱)}`,
      }
    case 'travel':
      return {
        title: `远行 · ${String(data?.当前区域 || '驿站')}`,
        sub: String(data?.驿站类型 || ''),
      }
    case 'inn':
      return {
        title: `投宿 · ${String(data?.场景 || '客栈')}`,
        sub: `金钱 ${fmtMoney(data?.金钱)} · 固定4时辰`,
      }
  }
}

export function CardInteractionModal({
  kind, data, loading, busy, error, onClose, onSubmit,
}: {
  kind: CardInteractionKind
  data?: any
  loading?: boolean
  busy?: boolean
  error?: string
  onClose: () => void
  onSubmit: (action: Record<string, unknown>) => void
}) {
  const [quantities, setQuantities] = useState<Record<string, string>>({})
  const [localError, setLocalError] = useState('')

  useEffect(() => {
    setQuantities({})
    setLocalError('')
  }, [kind, data])

  const heading = titleOf(kind, data)
  const quantityInput = (key: string, maximum: number, disabled: boolean) => (
    <input
      type="number"
      min={1}
      max={Math.max(1, maximum)}
      step={1}
      value={quantities[key] ?? '1'}
      disabled={disabled || busy}
      aria-label="数量"
      style={{ ...selectStyle, width: 62, boxSizing: 'border-box', padding: '4px 5px' }}
      onChange={event => {
        setLocalError('')
        setQuantities(values => ({ ...values, [key]: event.target.value }))
      }}
    />
  )

  const submitCounted = (
    key: string,
    maximum: number,
    action: Record<string, unknown>,
  ) => {
    const count = positiveCount(quantities[key] ?? '1', maximum)
    if (count == null) {
      setLocalError(`数量必须是 1～${maximum} 的整数`)
      return
    }
    setLocalError('')
    onSubmit({ ...action, 数量: count })
  }

  let body = null
  if (loading && !data) {
    body = <LoadingState text="读取交互内容中…" />
  } else if (kind === 'buy') {
    const items = Array.isArray(data?.货架) ? data.货架 : []
    const money = finiteNumber(data?.金钱)
    body = items.length ? (
      <PanelTable
        headers={['物品', '库存', '单价', '类型', '品级', '数量', '操作']}
        rows={items.map((item: any, index: number) => {
          const key = itemKey(item, index)
          const stock = Math.max(0, Math.floor(finiteNumber(item?.数量) ?? 1))
          const price = finiteNumber(item?.价格)
          const affordable = money != null && price != null && price > 0
            ? Math.floor(money / price)
            : stock
          const maximum = Math.min(stock, Math.max(0, affordable))
          const disabled = maximum < 1
          const action: Record<string, unknown> = {
            类型: '购买',
            卖家: String(data?.卖家 || ''),
            物品: String(item?.名称 || ''),
            商人: Boolean(data?.商人),
          }
          if (typeof data?.买家 === 'string' && data.买家) action.买家 = data.买家
          if (price != null && price >= 0) action.价格 = price
          return [
            String(item?.名称 || '—'),
            `×${stock}`,
            fmtMoney(price),
            [item?.类型, item?.子类型].filter(Boolean).join(' · ') || '—',
            itemGrade(item),
            quantityInput(key, maximum, disabled),
            <PanelButton
              active
              disabled={disabled || busy || !action.卖家 || !action.物品}
              onClick={() => submitCounted(key, maximum, action)}
            >
              {disabled ? '金钱/库存不足' : '购买'}
            </PanelButton>,
          ]
        })}
      />
    ) : <EmptyState>{String(data?.卖家 || '卖家')}暂无可售物品</EmptyState>
  } else if (kind === 'sell') {
    const items = Array.isArray(data?.可售物品) ? data.可售物品 : []
    body = items.length ? (
      <PanelTable
        headers={['物品', '持有', '估价', '类型', '品级', '数量', '操作']}
        rows={items.map((item: any, index: number) => {
          const key = itemKey(item, index)
          const stock = Math.max(0, Math.floor(finiteNumber(item?.数量) ?? 1))
          const price = finiteNumber(item?.价格)
          const action: Record<string, unknown> = {
            类型: '出售',
            买家: String(data?.买家 || ''),
            物品: String(item?.名称 || ''),
            商人: Boolean(data?.商人),
          }
          if (typeof data?.卖家 === 'string' && data.卖家) action.卖家 = data.卖家
          if (price != null && price >= 0) action.价格 = price
          return [
            String(item?.名称 || '—'),
            `×${stock}`,
            fmtMoney(price),
            [item?.类型, item?.子类型].filter(Boolean).join(' · ') || '—',
            itemGrade(item),
            quantityInput(key, stock, stock < 1),
            <PanelButton
              active
              disabled={stock < 1 || busy || !action.买家 || !action.物品}
              onClick={() => submitCounted(key, stock, action)}
            >
              出售
            </PanelButton>,
          ]
        })}
      />
    ) : <EmptyState>当前没有可出售的物品</EmptyState>
  } else if (kind === 'travel') {
    const routes = Array.isArray(data?.路线) ? data.路线 : []
    body = routes.length ? (
      <PanelTable
        headers={['目的地', '耗时', '费用', '操作']}
        rows={routes.map((route: any) => {
          const destination = String(route?.目的地 || '')
          const days = Math.max(0, Math.floor(finiteNumber(route?.耗时) ?? 0))
          const fee = Math.max(0, finiteNumber(route?.费用) ?? 0)
          return [
            destination || '—',
            `${days}天`,
            fmtMoney(fee),
            <PanelButton
              active
              disabled={busy || !destination}
              onClick={() => onSubmit({ 类型: '远行（舟车）', 目的地: destination })}
            >
              前往
            </PanelButton>,
          ]
        })}
      />
    ) : <EmptyState>此驿站暂无直达路线，需经他处换乘</EmptyState>
  } else {
    const levels = Array.isArray(data?.等级) ? data.等级 : []
    const money = finiteNumber(data?.金钱)
    const recovery: Record<string, string> = {
      '0.15': '上限15%/时辰',
      '0.2': '上限20%/时辰',
      '0.25': '上限25%/时辰',
    }
    body = levels.length ? (
      <PanelTable
        headers={['等级', '体力恢复', '气血/内力', '费用', '操作']}
        rows={levels.map((level: any) => {
          const name = String(level?.等级 || '')
          const duration = Math.max(1, Math.floor(finiteNumber(level?.时长) ?? 32))
          const unit = Math.max(0, finiteNumber(level?.每刻单价) ?? 0)
          const fee = unit * duration
          const poor = money != null && money < fee
          return [
            name || '—',
            `${finiteNumber(level?.体力每时辰) ?? 0}/时辰`,
            recovery[String(level?.气血内力比例)] || `上限${String(level?.气血内力比例 ?? 0)}/时辰`,
            fmtMoney(fee),
            <PanelButton
              active
              disabled={busy || poor || !name}
              onClick={() => onSubmit({
                类型: '休息', 等级: name, 时长: duration, 免费: false,
              })}
            >
              {poor ? '金钱不足' : '投宿'}
            </PanelButton>,
          ]
        })}
      />
    ) : <EmptyState>当前客栈没有可选房档</EmptyState>
  }

  return (
    <div style={{
      position: 'absolute', inset: 0, zIndex: 4, minHeight: 360,
      display: 'flex', flexDirection: 'column', boxSizing: 'border-box',
      borderRadius: 8, background: '#1a1612', color: '#e8dcc4', overflow: 'hidden',
    }}>
      <div style={{
        flex: '0 0 auto', display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: 12,
        padding: '9px 12px', background: '#241d16', borderBottom: '1px solid #6f5527',
      }}>
        <div style={{ minWidth: 0 }}>
          <div style={{ color: '#c8a456', fontWeight: 600, letterSpacing: 1 }}>{heading.title}</div>
          {heading.sub ? <div style={{ marginTop: 1, color: '#9a8c6e', fontSize: 11 }}>{heading.sub}</div> : null}
        </div>
        <button
          type="button"
          aria-label="关闭交互面板"
          disabled={busy}
          onClick={onClose}
          style={{
            flex: '0 0 auto', padding: '1px 7px', color: '#c8a456', background: 'transparent',
            border: '1px solid #6f5527', borderRadius: 5, cursor: busy ? 'default' : 'pointer',
            opacity: busy ? 0.45 : 1, fontSize: 14,
          }}
        >×</button>
      </div>
      <div style={{ flex: '1 1 auto', minHeight: 0, padding: '10px 12px 14px', overflow: 'auto' }}>
        <PanelNotice kind="error">{localError || error}</PanelNotice>
        {body}
        {kind === 'inn' && data ? (
          <div style={{ marginTop: 8, color: '#9a8c6e', fontSize: 11 }}>
            投宿结算固定为4时辰（32刻）；露宿不经此面板。
          </div>
        ) : null}
      </div>
      {busy ? (
        <div style={{ flex: '0 0 auto', padding: '7px 12px', color: '#9a8c6e', borderTop: '1px solid #3a2f22', fontSize: 11 }}>
          正在结算…
        </div>
      ) : null}
    </div>
  )
}
