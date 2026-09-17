// 拉取标题页：通过 dsh command remote 直调 Host（不经 LLM）。
// Host 的 wuxia-title 隐藏命令直调 engine 开始游戏，返回标题数据供入口按钮直出开始界面。

export interface TitleResponse {
  next_slot: number
  存档列表: any[]
  版本: string
}

function transportMessage(error: any): string {
  const code = error?.code ? `${error.code}: ` : ''
  return `${code}${error?.message || '未知传输错误'}`
}

export async function requestTitle(remote: any, sessionId: string): Promise<TitleResponse> {
  const executed = await remote.commands.execute(sessionId, '/wuxia-title', [])
  if (!executed?.ok) {
    throw new Error(`标题页命令调用失败：${transportMessage(executed?.error)}`)
  }
  if (!executed.value) throw new Error('标题页命令未注册')

  const result = executed.value.result
  if (result?.kind === 'error') throw new Error(result.text || '标题页命令执行失败')
  if (typeof result?.text !== 'string' || !result.text) throw new Error('标题页命令未返回数据')

  let parsed: any
  try {
    parsed = JSON.parse(result.text)
  } catch {
    throw new Error('标题页命令返回了无效 JSON')
  }
  if (!parsed || typeof parsed.next_slot !== 'number'
    || !Number.isInteger(parsed.next_slot) || parsed.next_slot <= 0
    || !Array.isArray(parsed.存档列表)) {
    throw new Error('标题页命令返回格式不完整')
  }
  return {
    next_slot: parsed.next_slot,
    存档列表: parsed.存档列表,
    版本: typeof parsed.版本 === 'string' ? parsed.版本 : '',
  }
}

export type TitleRequest = () => Promise<TitleResponse>
