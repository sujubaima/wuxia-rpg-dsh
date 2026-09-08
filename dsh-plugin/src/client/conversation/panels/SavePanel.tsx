import { useCallback, useEffect, useState } from 'react'
import {
  EmptyState, engineError, formatSaveTimestamp, LoadingState, PanelButton,
  PanelDescription, PanelNotice, PanelTable, resultNotice, selectStyle, type PanelProps,
} from './PanelPrimitives'

export function SavePanel({ slot, request }: PanelProps) {
  const [label, setLabel] = useState('')
  const [data, setData] = useState<any>(null)
  const [loading, setLoading] = useState(true)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const [notice, setNotice] = useState('')

  const refresh = useCallback(async (showLoading = true) => {
    if (showLoading) setLoading(true)
    setError('')
    try {
      const response = await request(slot, [{ 类型: '存档列表' }])
      const next = response.results[0]
      const err = engineError(next)
      if (err) throw new Error(err)
      setData(next)
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : String(caught))
    } finally {
      setLoading(false)
    }
  }, [request, slot])

  useEffect(() => { void refresh() }, [refresh])

  const save = async () => {
    if (busy) return
    const nextLabel = label.trim()
    if (!nextLabel) {
      setError('请先填写存档名')
      return
    }
    setBusy(true)
    setError('')
    setNotice('')
    try {
      const response = await request(slot, [{ 类型: '保存游戏', 标签: nextLabel }])
      const result = response.results[0]
      const err = engineError(result)
      if (err) throw new Error(err)
      setNotice(resultNotice(result) || `已保存游戏 ${nextLabel}`)
      setLabel('')
      await refresh(false)
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : String(caught))
    } finally {
      setBusy(false)
    }
  }

  const groups = Array.isArray(data?.存档列表) ? data.存档列表 : []
  const current = groups.find((entry: any) => Number(entry?.slot) === slot) ?? groups[0]
  const saves = Array.isArray(current?.saves) ? current.saves : []
  const progress = String(current?.进度 || '')

  return (
    <div>
      <PanelDescription>
        保存 Slot_{slot}{current?.角色名 ? ` · ${current.角色名}` : ''} 当前已落盘的游历进度；存档名必填。
      </PanelDescription>
      <div style={{ display: 'flex', alignItems: 'center', gap: 6, flexWrap: 'wrap', marginBottom: 8 }}>
        <input
          type="text"
          value={label}
          maxLength={60}
          disabled={busy}
          placeholder="存档名（必填）"
          aria-label="存档名"
          style={{ ...selectStyle, width: 220, boxSizing: 'border-box' }}
          onChange={event => setLabel(event.target.value)}
          onKeyDown={event => {
            if (event.key !== 'Enter') return
            event.preventDefault()
            void save()
          }}
        />
        <PanelButton active disabled={busy || loading} onClick={() => void save()}>
          {busy ? '保存中…' : '保存进度'}
        </PanelButton>
        <PanelButton disabled={busy || loading} onClick={() => void refresh()}>
          {loading ? '刷新中…' : '刷新列表'}
        </PanelButton>
      </div>
      <PanelNotice kind="error">{error}</PanelNotice>
      <PanelNotice kind="notice">{notice}</PanelNotice>
      {loading && !data ? <LoadingState text="读取存档列表中…" /> : saves.length ? (
        <PanelTable
          headers={['存档', '时间', '标签 / 进度']}
          rows={saves.map((save: any, index: number) => [
            `File_${save?.序号 ?? index + 1}`,
            formatSaveTimestamp(save?.时间戳),
            String(save?.label || progress || '无'),
          ])}
        />
      ) : <EmptyState>当前角色尚无存档点，填写存档名即可保存</EmptyState>}
    </div>
  )
}
