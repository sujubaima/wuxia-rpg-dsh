import { useState } from 'react'
import { useGameStore, type GateSave } from '../../store'
import { Btn } from '../ui'

function SaveItem({ s }: { s: GateSave }) {
  const [open, setOpen] = useState(false)
  const sendLoadArchive = useGameStore(st => st.sendLoadArchive)
  const uiOp = useGameStore(st => st.uiOp)
  const loadGateSaves = useGameStore(st => st.loadGateSaves)
  const n = (s.saves || []).length

  return (
    <div className="savewrap">
      <div className="saveitem">
        <Btn className="exptoggle" disabled={!n} onClick={() => setOpen(o => !o)}>
          {n ? (open ? '▾ ' : '▸ ') + n + '点' : '—'}
        </Btn>
        <div className="nm">
          <div className="lb">slot {s.slot} · {s.角色名 || '（无名）'}</div>
          <div className="ts">最近存档 {s.最近存档 || '—'}</div>
        </div>
        <Btn onClick={() => {
          if (confirm(`读取 slot ${s.slot}（${s.角色名 || ''}）的最新存档？`))
            sendLoadArchive(s.slot, s.最近存档 || '', s.角色名 || s.最近存档 || '')
        }}>读取最新</Btn>
        <Btn danger onClick={() => uiOp({ 类型: '删除存档', 槽位: s.slot }, {
          confirm: `删除 slot ${s.slot}（${s.角色名 || ''}）整个角色档？不可恢复！`,
          refresh: loadGateSaves,
        })}>删档</Btn>
      </div>
      {open && (
        <div className="savesub">
          {(s.saves || []).map((sv, i) => (
            <div className="savesubitem" key={i}>
              <span className="lb2">{sv.label || '（未命名）'}</span>
              <span className="ts2">#{sv.序号} {sv.时间戳}</span>
              <Btn onClick={() => {
                if (confirm(`读取 slot ${s.slot} 的存档「${sv.label || sv.时间戳}」？`))
                  sendLoadArchive(s.slot, sv.时间戳 || '', sv.label || sv.时间戳 || '')
              }}>读取</Btn>
            </div>
          ))}
        </div>
      )}
    </div>
  )
}

export function Gate() {
  const gateMode = useGameStore(s => s.gateMode)
  const gateSaves = useGameStore(s => s.gateSaves)
  const gateSaveCnt = useGameStore(s => s.gateSaveCnt)
  const gateLoading = useGameStore(s => s.gateLoading)
  const openWizard = useGameStore(s => s.openWizard)
  if (!gateMode) return null

  return (
    <div id="gateTop">
      <div className="gate-hero">
        <pre className="logo">{`██╗    ██╗██╗   ██╗██╗  ██╗
██║    ██║██║   ██║╚██╗██╔╝
██║ █╗ ██║██║   ██║ ╚███╔╝
██║███╗██║██║   ██║ ██╔██╗
╚███╔███╔╝╚██████╔╝██╔╝ ██╗
 ╚══╝╚══╝  ╚═════╝ ╚═╝  ╚═╝

        ── 武 侠 R P G ──`}</pre>
        <div className="gate-sub">江湖路远，剑未出鞘。少侠，从何而起？</div>
        <div className="gate-meta">作者：可乐酸橙　版本：v0.9.8　<span>存档：{gateSaveCnt} 个</span></div>
        <div className="gate-hint">点上方按钮开新档，或读取存档续旧缘。</div>
      </div>
      <div className="gate-actions">
        <Btn primary onClick={openWizard}>＋ 创建角色</Btn>
      </div>
      <div id="gateSaves">
        {gateLoading ? (
          <div className="ph" style={{ textAlign: 'center' }}>…读取存档列表…</div>
        ) : gateSaves.length === 0 ? (
          <div className="ph" style={{ textAlign: 'center' }}>尚无存档可续，在下方描述你的角色开创新篇。</div>
        ) : (
          gateSaves.map(s => <SaveItem key={s.slot} s={s} />)
        )}
      </div>
    </div>
  )
}
