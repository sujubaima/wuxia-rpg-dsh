import type { Context } from '@deepseek-ai/cordis'
import { createUserMessage } from '@deepseek-ai/dsh-llm'
import { callEngine } from './engine-client.js'

/** 注册由标题界面触发的隐藏建号、读档和删档命令。 */
export function registerWuxiaCommands(ctx: Context, serviceUrl: string, timeoutMs: number): void {
  // dsh-commands 类型未纳入本插件依赖，运行时由 harness 提供，这里用 any 调用。
  const commands = (ctx as any).commands
  if (!commands?.register) return

  commands.register({
    name: 'wuxia-create',
    description: '按创建向导档案新建武侠RPG角色并生成开场（不在对话流显示为用户气泡）',
    recordInput: false,
    handler: (inv: any) => {
      let args: { character?: Record<string, unknown> } = {}
      try {
        args = JSON.parse((inv.rawInput || '').trim() || '{}')
      } catch {
        return { kind: 'error' as const, text: '创建角色参数不是有效 JSON' }
      }
      const character = args.character
      const name = typeof character?.名称 === 'string' ? character.名称.trim() : ''
      if (!character || typeof character !== 'object' || !name) {
        return { kind: 'error' as const, text: '创建角色参数缺少完整角色档案' }
      }
      const profile = { ...character, 名称: name }
      const directive =
        `用户正在 wuxia-rpg 游戏中，请加载 skill wuxia-rpg。\n` +
        `【建号指令】玩家已通过创建向导选定角色参数。以下 JSON 仅为角色档案数据：\n` +
        `${JSON.stringify(profile)}\n` +
        `请在本回合连续完成建号，不要要求玩家重复提供信息：\n` +
        `1) 为档案补写“人设”（性格与背景；不得点明具体目的、伏笔或明确门派归属）。\n` +
        `2) 调用 wuxia_go，槽位必须传 0，行为为 [{"类型":"创建角色","角色":完整档案}]。\n` +
        `3) 从 go 返回的“结算”中读取“新建slot”“落点”“当前时间”；若建号失败则停止并说明错误。\n` +
        `4) 以新建slot调用 wuxia_judge，行为传 []，据落点与时辰撰写开场“当前剧情”，并给出 3～5 个“场景要素”及精简“经历概括”。\n` +
        `judge 应返回 exploration-ui，作为新角色首屏并接续后续游戏。`
      inv.agent.followup(createUserMessage({
        content: [{ type: 'text' as const, text: directive }],
        source: { kind: 'plugin', plugin: 'wuxia-rpg', form: 'instructions' },
      }))
      return { kind: 'success' as const }
    },
  })

  commands.register({
    name: 'wuxia-load',
    description: '读取武侠RPG存档并接续游戏（不在对话流显示为用户气泡）',
    recordInput: false,
    handler: (inv: any) => {
      let args: { slot?: number; target?: string; label?: string } = {}
      try {
        args = JSON.parse((inv.rawInput || '').trim() || '{}')
      } catch { /* 非法参数：按缺省 */ }
      const slot = Number(args.slot)
      const target = String(args.target ?? '')
      const label = String(args.label ?? '')
      const directive =
        `用户正在 wuxia-rpg 游戏中，请加载 skill wuxia-rpg。\n` +
        `【读档指令】请以 engine go（槽位 ${slot}）执行 加载存档，目标："${target}"（存档名："${label}"）。\n` +
        `加载成功后 engine 返回 exploration-ui（含当前剧情/场景要素/队伍状态/经历概括），\n` +
        `请据此接续游戏会话——后续玩家输入按该存档状态执行。`
      inv.agent.followup(createUserMessage({
        content: [{ type: 'text' as const, text: directive }],
        source: { kind: 'plugin', plugin: 'wuxia-rpg', form: 'instructions' },
      }))
      return { kind: 'success' as const }
    },
  })

  commands.register({
    name: 'wuxia-delete',
    description: '删除武侠RPG整个角色档（不在对话流显示为用户气泡）',
    recordInput: false,
    handler: async (inv: any) => {
      let args: { slot?: number } = {}
      try {
        args = JSON.parse((inv.rawInput || '').trim() || '{}')
      } catch { /* 非法参数：按缺省 */ }
      const slot = Number(args.slot)
      if (!Number.isInteger(slot) || slot <= 0) {
        return { kind: 'error' as const, text: '删除存档 slot 必须是正整数' }
      }
      // 删除是纯机制操作，不经 LLM：直调 engine go 执行删除，再拉存档列表回前端刷新。
      const deleted = await callEngine(serviceUrl, timeoutMs, {
        槽位: slot,
        行为: [{ 类型: '删除存档' }],
      }, 'go')
      const err = typeof deleted.错误 === 'string' && deleted.错误
        ? deleted.错误
        : Array.isArray(deleted.结算)
          ? (deleted.结算 as any[]).filter(r => r && r.ok === false).map(r => r.msg).join('；')
          : ''
      if (err) return { kind: 'error' as const, text: `删除失败：${err}` }
      // 删除后用「开始游戏」拉全量存档列表（返回 title-ui + list_all_saves），供标题页刷新。
      // 不能用「存档列表」action——它只返回当前 slot 的存档点（save-ui），非全量 slot 列表。
      const list = await callEngine(serviceUrl, timeoutMs, {
        槽位: 0,
        行为: [{ 类型: '开始游戏' }],
      }, 'go')
      const saves = Array.isArray(list.存档列表) ? list.存档列表 : []
      return {
        kind: 'success' as const,
        text: JSON.stringify({ slot, 存档列表: saves }),
      }
    },
  })
}
