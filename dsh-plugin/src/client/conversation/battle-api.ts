export type BattleAction = Record<string, unknown>

export type BattleCommandRequest =
  | {
    operation: 'start'
    slot: number
    allies: string[]
    enemies: string[]
    allowEscape: boolean
    control: string
  }
  | { operation: 'act'; slot: number; action: BattleAction }
  | { operation: 'advance'; slot: number }
  | {
    operation: 'conclude'
    slot: number
    final: Record<string, unknown>
    decisions?: { 角色: string; 决定: '杀' | '放' }[]
  }

export interface BattleCommandResponse {
  result?: Record<string, any>
  committed?: boolean
  pendingAdvance?: boolean
  followup?: boolean
}

export type BattleRequest = (
  request: BattleCommandRequest,
) => Promise<BattleCommandResponse>

function transportMessage(error: any): string {
  const code = error?.code ? `${error.code}: ` : ''
  return `${code}${error?.message || '未知传输错误'}`
}

/** 通过隐藏 command 调 Host 完成战斗步骤，不在对话流产生用户气泡。 */
export async function requestBattle(
  remote: any,
  sessionId: string,
  request: BattleCommandRequest,
): Promise<BattleCommandResponse> {
  const line = `/wuxia-battle ${JSON.stringify(request)}`
  const executed = await remote.commands.execute(sessionId, line, [])
  if (!executed?.ok) {
    throw new Error(`战斗命令调用失败：${transportMessage(executed?.error)}`)
  }
  if (!executed.value) throw new Error('战斗命令未注册')

  const result = executed.value.result
  if (result?.kind === 'error') throw new Error(result.text || '战斗命令执行失败')
  if (typeof result?.text !== 'string' || !result.text) throw new Error('战斗命令未返回数据')

  let parsed: any
  try {
    parsed = JSON.parse(result.text)
  } catch {
    throw new Error('战斗命令返回了无效 JSON')
  }
  if (!parsed || typeof parsed !== 'object') throw new Error('战斗命令返回格式不完整')
  return {
    ...(parsed.result && typeof parsed.result === 'object' ? { result: parsed.result } : {}),
    ...(typeof parsed.committed === 'boolean' ? { committed: parsed.committed } : {}),
    ...(typeof parsed.pendingAdvance === 'boolean' ? { pendingAdvance: parsed.pendingAdvance } : {}),
    ...(parsed.followup === true ? { followup: true } : {}),
  }
}
