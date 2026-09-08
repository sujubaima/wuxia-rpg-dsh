export type PanelAction = Record<string, unknown>

export interface PanelResponse {
  results: Record<string, any>[]
  state?: Record<string, any>
  view?: Record<string, any>
  followup?: boolean
}

export type PanelRequest = (
  slot: number,
  actions: PanelAction[],
) => Promise<PanelResponse>

function transportMessage(error: any): string {
  const code = error?.code ? `${error.code}: ` : ''
  return `${code}${error?.message || '未知传输错误'}`
}

/** 通过 dsh command remote 调 Host，避免浏览器直连 engine。 */
export async function requestPanel(
  remote: any,
  sessionId: string,
  slot: number,
  actions: PanelAction[],
): Promise<PanelResponse> {
  const line = `/wuxia-panel ${JSON.stringify({ slot, actions })}`
  const executed = await remote.commands.execute(sessionId, line, [])
  if (!executed?.ok) {
    throw new Error(`面板命令调用失败：${transportMessage(executed?.error)}`)
  }
  if (!executed.value) throw new Error('面板命令未注册')

  const result = executed.value.result
  if (result?.kind === 'error') throw new Error(result.text || '面板命令执行失败')
  if (typeof result?.text !== 'string' || !result.text) throw new Error('面板命令未返回数据')

  let parsed: any
  try {
    parsed = JSON.parse(result.text)
  } catch {
    throw new Error('面板命令返回了无效 JSON')
  }
  if (!parsed || !Array.isArray(parsed.results)) throw new Error('面板命令返回格式不完整')
  return {
    results: parsed.results,
    ...(parsed.state && typeof parsed.state === 'object' ? { state: parsed.state } : {}),
    ...(parsed.view && typeof parsed.view === 'object' ? { view: parsed.view } : {}),
    ...(parsed.followup === true ? { followup: true } : {}),
  }
}
