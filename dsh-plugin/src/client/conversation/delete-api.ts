// 删除存档：通过 dsh command remote 直调 Host（不经 LLM）。
// Host 的 wuxia-delete 隐藏命令直调 engine 删除并返回刷新后的存档列表。

export interface DeleteSaveResponse {
  slot: number
  存档列表: any[]
}

function transportMessage(error: any): string {
  const code = error?.code ? `${error.code}: ` : ''
  return `${code}${error?.message || '未知传输错误'}`
}

export async function requestDelete(
  remote: any,
  sessionId: string,
  slot: number,
): Promise<DeleteSaveResponse> {
  const line = `/wuxia-delete ${JSON.stringify({ slot })}`
  const executed = await remote.commands.execute(sessionId, line, [])
  if (!executed?.ok) {
    throw new Error(`删除命令调用失败：${transportMessage(executed?.error)}`)
  }
  if (!executed.value) throw new Error('删除命令未注册')

  const result = executed.value.result
  if (result?.kind === 'error') throw new Error(result.text || '删除命令执行失败')
  if (typeof result?.text !== 'string' || !result.text) throw new Error('删除命令未返回数据')

  let parsed: any
  try {
    parsed = JSON.parse(result.text)
  } catch {
    throw new Error('删除命令返回了无效 JSON')
  }
  if (!parsed || typeof parsed.slot !== 'number' || !Array.isArray(parsed.存档列表)) {
    throw new Error('删除命令返回格式不完整')
  }
  return { slot: parsed.slot, 存档列表: parsed.存档列表 }
}

export type DeleteRequest = (slot: number) => Promise<DeleteSaveResponse>
