import type { Context } from '@deepseek-ai/cordis'
import { createUserMessage } from '@deepseek-ai/dsh-llm'
import type { JsonValue } from '@deepseek-ai/dsh-tools'
import { callEngine } from './engine-client.js'

const MAX_ACTIONS = 4

type FieldValidator = (value: unknown) => boolean

const stringValue: FieldValidator = value => typeof value === 'string'
const booleanValue: FieldValidator = value => typeof value === 'boolean'
const positiveInteger: FieldValidator = value => typeof value === 'number' && Number.isInteger(value) && value > 0
const nonNegativeNumber: FieldValidator = value => typeof value === 'number' && Number.isFinite(value) && value >= 0

const ACTION_FIELDS: Record<string, Readonly<Record<string, FieldValidator>>> = {
  查看背包: { 筛选类型: stringValue, 筛选子类型: stringValue },
  配置物品: { 操作: stringValue, 物品: stringValue },
  使用物品: { 物品: stringValue },
  配置装备: { 操作: stringValue, 槽位: stringValue, 物品: stringValue, 角色: stringValue },
  配置武学: { 操作: stringValue, 武学: stringValue, 运转心法: stringValue, 角色: stringValue },
  武学列表: { 角色: stringValue },
  武学精进: { 武学: stringValue, 操作: stringValue },
  查看地图: {},
  查看线索: {},
  保存游戏: { 标签: stringValue },
  存档列表: {},
  角色信息: { 角色: stringValue },
  购买: {
    卖家: stringValue, 物品: stringValue, 数量: positiveInteger,
    价格: nonNegativeNumber, 商人: booleanValue, 买家: stringValue, 标签: stringValue,
  },
  出售: {
    买家: stringValue, 物品: stringValue, 数量: positiveInteger,
    价格: nonNegativeNumber, 商人: booleanValue, 卖家: stringValue,
  },
  '远行（舟车）': { 目的地: stringValue },
  休息: { 等级: stringValue, 时长: positiveInteger, 免费: booleanValue },
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return value !== null && typeof value === 'object' && !Array.isArray(value)
}

function isMutation(action: Record<string, unknown>): boolean {
  switch (action.类型) {
    case '使用物品':
    case '保存游戏':
      return true
    case '配置物品':
    case '配置装备':
      return typeof action.操作 === 'string' && action.操作.length > 0
    case '配置武学':
      return (typeof action.操作 === 'string' && action.操作.length > 0) || action.运转心法 !== undefined
    case '武学精进':
      return typeof action.操作 === 'string' && action.操作.length > 0
    case '购买':
    case '出售':
      return typeof action.物品 === 'string' && action.物品.trim().length > 0
    case '远行（舟车）':
      return typeof action.目的地 === 'string' && action.目的地.trim().length > 0
    case '休息':
      return typeof action.等级 === 'string' && action.等级.trim().length > 0
        && typeof action.时长 === 'number' && action.时长 > 0
    default:
      return false
  }
}

function needsNarration(
  action: Record<string, unknown>,
  result: Record<string, JsonValue>,
): boolean {
  if (!isMutation(action)) return false
  if (!['购买', '出售', '远行（舟车）', '休息'].includes(String(action.类型))) return false
  if (result.界面 !== undefined || result.错误 !== undefined) return false
  const failed = Array.isArray(result.结算)
    && result.结算.some(entry => isRecord(entry) && entry.ok === false)
  return !failed
}

function narrationDirective(
  slot: number,
  action: Record<string, unknown>,
  result: Record<string, JsonValue>,
): string {
  const stateKeys = [
    '结算', '当前位置', '当前时间', '时间', '时段', '体力', '金钱',
    '队伍状态', '当前场景类型', '区域', 'GM参考', '状态提示',
  ]
  const state = Object.fromEntries(
    stateKeys.filter(key => result[key] !== undefined).map(key => [key, result[key]]),
  )
  const continuation = action.类型 === '远行（舟车）'
    ? '按 GM参考及 skill 规则完成随机事件和必要判定，据真实结算续写本回合剧情'
    : action.类型 === '休息'
      ? '承接本次投宿/休息剧情，据真实结算续写本回合'
      : '据真实结算续写本回合剧情'
  return (
    `用户正在 wuxia-rpg 游戏中，请加载 skill wuxia-rpg。\n` +
    `【卡内交互结算续写】前端已直接调用 engine go 完成机制结算并落盘。\n` +
    `行为：${JSON.stringify(action)}\n` +
    `go 返回状态：${JSON.stringify(state)}\n` +
    `不得再次调用 wuxia_go，不得重复扣除金钱、体力或推进时间。\n` +
    `请从 go 之后的推演阶段继续：${continuation}，然后以槽位 ${slot} 调用 wuxia_judge ` +
    `落盘当前剧情、场景要素和经历概括。\n` +
    `wuxia_judge 应返回 exploration-ui；渲染模式为 dsh 时按 skill 要求保持正文静默。`
  )
}

function validateActions(value: unknown): { actions?: Record<string, unknown>[]; error?: string } {
  if (!Array.isArray(value) || value.length === 0 || value.length > MAX_ACTIONS) {
    return { error: `actions 必须包含 1～${MAX_ACTIONS} 个行为` }
  }

  const actions: Record<string, unknown>[] = []
  let mutations = 0
  for (const item of value) {
    if (!isRecord(item)) return { error: '每个 action 必须是 JSON 对象' }
    const type = typeof item.类型 === 'string' ? item.类型 : ''
    const fields = ACTION_FIELDS[type]
    if (!fields) return { error: `不允许的面板行为：${type || '（缺少类型）'}` }
    const extra = Object.keys(item).find(key => key !== '类型' && !(key in fields))
    if (extra) return { error: `${type} 不支持参数：${extra}` }
    const invalid = Object.entries(item).find(
      ([key, entry]) => key !== '类型' && !fields[key]?.(entry),
    )
    if (invalid) return { error: `${type} 的参数 ${invalid[0]} 类型或取值无效` }
    if (isMutation(item)) mutations += 1
    actions.push(item)
  }
  if (mutations > 1) return { error: '一次面板请求最多执行一个修改行为' }
  return { actions }
}

function pickState(result: Record<string, JsonValue>): Record<string, JsonValue> | undefined {
  if (!Array.isArray(result.队伍状态)
    && typeof result.体力 !== 'number'
    && typeof result.金钱 !== 'number') return undefined
  return {
    ...(typeof result.槽位 === 'number' ? { 槽位: result.槽位 } : {}),
    ...(Array.isArray(result.队伍状态) ? { 队伍状态: result.队伍状态 } : {}),
    ...(typeof result.体力 === 'number' ? { 体力: result.体力 } : {}),
    ...(typeof result.金钱 === 'number' ? { 金钱: result.金钱 } : {}),
  }
}

/** 注册即时 engine 命令；特殊交互结算无界面时按 Web UI 语义交给 LLM 续写。 */
export function registerWuxiaPanelCommand(ctx: Context, serviceUrl: string, timeoutMs: number): void {
  const commands = (ctx as any).commands
  if (!commands?.register) return

  commands.register({
    name: 'wuxia-panel',
    description: '读取或配置武侠RPG队伍浮窗面板',
    recordInput: false,
    handler: async (inv: any) => {
      let args: { slot?: unknown; actions?: unknown } = {}
      try {
        args = JSON.parse((inv.rawInput || '').trim() || '{}')
      } catch {
        return { kind: 'error' as const, text: '面板参数不是有效 JSON' }
      }

      const slot = Number(args.slot)
      if (!Number.isInteger(slot) || slot <= 0) {
        return { kind: 'error' as const, text: '面板 slot 必须是正整数' }
      }
      const checked = validateActions(args.actions)
      if (!checked.actions) {
        return { kind: 'error' as const, text: checked.error || '面板行为无效' }
      }

      const results: Record<string, JsonValue>[] = []
      let state: Record<string, JsonValue> | undefined
      let view: Record<string, JsonValue> | undefined
      let returnedInterface = false
      let mutated = false
      let followup = false
      for (const action of checked.actions) {
        const result = await callEngine(serviceUrl, timeoutMs, { 槽位: slot, 行为: [action] }, 'go')
        results.push(result)
        state = pickState(result) ?? state
        mutated ||= isMutation(action)
        returnedInterface ||= result.界面 !== undefined
        if (isMutation(action) && result.界面 === 'exploration-ui') view = result
        if (!followup && needsNarration(action, result)) {
          inv.agent.followup(createUserMessage({
            content: [{ type: 'text' as const, text: narrationDirective(slot, action, result) }],
            source: { kind: 'plugin', plugin: 'wuxia-rpg', form: 'instructions' },
          }))
          followup = true
        }
      }

      // 仅无界面机械修改需要回放游历；任何已有界面（含战前/战斗界面）都必须原样保留。
      if (mutated && !followup && !returnedInterface) {
        const latest = await callEngine(
          serviceUrl,
          timeoutMs,
          { 槽位: slot, 行为: [{ 类型: '返回游戏' }] },
          'go',
        )
        state = pickState(latest) ?? state
        view = latest
      }

      return {
        kind: 'success' as const,
        text: JSON.stringify({
          results,
          ...(state ? { state } : {}),
          ...(view ? { view } : {}),
          ...(followup ? { followup: true } : {}),
        }),
      }
    },
  })
}
