import { useCallback, useEffect, useState } from 'react'
import {
  EmptyState, engineError, formatSaveTimestamp, LoadingState, PanelButton, PanelDescription,
  PanelNotice, PanelTable, type PanelProps,
} from './PanelPrimitives'

function loadCommand(slot: number, target: string, label: string): string {
  return `/wuxia-load ${JSON.stringify({ slot, target, label })}`
}

export function LoadPanel({
  slot, request, command, onLoadRequested,
}: PanelProps & {
  command?: (line: string) => void
  onLoadRequested?: () => void
}) {
  const [data, setData] = useState<any>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')

  const refresh = useCallback(async () => {
    setLoading(true)
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

  const groups = Array.isArray(data?.存档列表) ? data.存档列表 : []
  const current = groups.find((entry: any) => Number(entry?.slot) === slot) ?? groups[0]
  const saves = Array.isArray(current?.saves) ? current.saves : []
  const progress = String(current?.进度 || '')

  const load = (save: any, index: number) => {
    if (!command) return
    const target = String(save?.时间戳 || '')
    if (!target) {
      setError('该存档缺少时间戳，无法读取')
      return
    }
    const file = `File_${save?.序号 ?? index + 1}`
    const label = String(save?.label || progress || file)
    if (!window.confirm(`读取「${file} · ${label}」？当前尚未保存的进度将会丢失。`)) return
    command(loadCommand(slot, target, label))
    onLoadRequested?.()
  }

  return (
    <div>
      <PanelDescription>
        仅显示当前 Slot_{slot}{current?.角色名 ? ` · ${current.角色名}` : ''} 的存档点，最新存档排在最前。
      </PanelDescription>
      <div style={{ marginBottom: 8 }}>
        <PanelButton disabled={loading} onClick={() => void refresh()}>{loading ? '刷新中…' : '刷新'}</PanelButton>
      </div>
      <PanelNotice kind="error">{error}</PanelNotice>
      {loading && !data ? <LoadingState text="读取存档列表中…" /> : saves.length ? (
        <PanelTable
          headers={['存档', '时间', '标签 / 进度', '操作']}
          rows={saves.map((save: any, index: number) => [
            `File_${save?.序号 ?? index + 1}`,
            formatSaveTimestamp(save?.时间戳),
            String(save?.label || progress || '无'),
            <PanelButton
              active
              disabled={!command}
              title={command ? '读取此存档' : '当前会话暂不可执行读档命令'}
              onClick={() => load(save, index)}
            >
              读取
            </PanelButton>,
          ])}
        />
      ) : <EmptyState>当前角色尚无可读取存档</EmptyState>}
    </div>
  )
}
