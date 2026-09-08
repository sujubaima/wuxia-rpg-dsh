import { useCallback, useEffect, useState } from 'react'
import { fetchUi } from '../../api'
import { useGameStore } from '../../store'
import { Btn } from '../ui'
import { CardShell, LoadingCard } from './CardPanel'
import type { EngineResult } from '../../types'

export function SaveView() {
  const uiOp = useGameStore(s => s.uiOp)
  const sendLoadArchive = useGameStore(s => s.sendLoadArchive)
  const currentSlot = useGameStore(s => s.currentSlot)
  const [label, setLabel] = useState('')
  const [d, setD] = useState<EngineResult | null>(null)
  const refresh = useCallback(async () => { setD(await fetchUi({ 类型: '存档列表' })) }, [])
  useEffect(() => { void refresh() }, [refresh])
  const entry = (d?.存档列表 as any[])?.[0]
  const saves = (entry?.saves as any[]) || []
  if (!d) return <LoadingCard title="存档" />
  return (
    <CardShell title="存档" desc="当前 slot 的存档点。危险操作均有二次确认。">
      <div style={{ marginBottom: 10 }}>
        <input className="uibtn" placeholder="存档名（必填）" style={{ width: 180 }} value={label}
          onChange={e => setLabel(e.target.value)} />{' '}
        <Btn primary onClick={() => {
          if (!label.trim()) { useGameStore.getState().addSysLine('保存游戏须填写存档名'); return }
          uiOp({ 类型: '保存游戏', 标签: label.trim() }, { refresh })
        }}>保存进度</Btn>
      </div>
      {!entry ? <div className="ph">当前 slot 无存档点，或 slot 未创建（去标题 TAB 读档）。</div> : (
        <>
          <div className="ph">slot {entry.slot} ｜ {entry.角色名 || ''} ｜ 共 {saves.length} 个存档点</div>
          {saves.map((s, i) => (
            <div className="saveitem" key={i}>
              <div className="nm">
                <div className="lb">{s.label || '（未命名）'}</div>
                <div className="ts">#{s.序号} · {s.时间戳}</div>
              </div>
              <Btn onClick={() => { if (confirm(`读取存档「${s.label || s.时间戳}」？当前未保存进度将被覆盖。`)) sendLoadArchive(currentSlot, s.时间戳, s.label || s.时间戳) }}>读档</Btn>
              <Btn danger onClick={() => uiOp({ 类型: '删除存档', 目标: s.时间戳 }, { confirm: `删除存档点「${s.label || s.时间戳}」？不可恢复。`, refresh })}>删除</Btn>
            </div>
          ))}
          <Btn danger onClick={() => uiOp({ 类型: '删除存档' }, { confirm: `删除 slot ${entry.slot} 整个角色档（${entry.角色名 || ''}）？不可恢复，请再次确认。`, refresh })}>删除整个角色档</Btn>
        </>
      )}
    </CardShell>
  )
}
