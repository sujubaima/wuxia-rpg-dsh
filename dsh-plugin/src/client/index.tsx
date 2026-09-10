// 武侠RPG dsh Client 入口：注册 conversation event、回合卡片和队伍浮窗。

import { PartyFloat } from './conversation/PartyFloat'
import { AssistantThinkNode } from './conversation/AssistantThinkNode'
import { requestDelete } from './conversation/delete-api'
import { requestBattle } from './conversation/battle-api'
import { requestPanel } from './conversation/panel-api'
import { WuxiaTurnTail } from './conversation/WuxiaTurnTail'
import { WuxiaView } from './conversation/WuxiaView'
import { selectWuxiaResults, wuxiaDefinition } from './conversation/wuxia-data'
import { turnActivityOf } from './conversation/turn-activity'

export const name = 'wuxia-rpg-client'
export const inject = ['slots', 'sessions', 'uiConversation', 'remote', 'remote.commands']

function HiddenPanelCommand() {
  return null
}

export function apply(ctx: any): void {
  const sessions = ctx.sessions

  ctx.uiConversation.events.register(wuxiaDefinition)

  ctx.slots.inject('conversation.view', () => ctx.slots.register({
    name: 'conversation.view',
    id: 'wuxia',
    order: 20,
    label: () => '武侠',
    inject: (sessionId: unknown) => ({ sessionId }),
  }, WuxiaView))

  // session.command 直接调用隐藏斜杠命令；composer draft 每次点击时重新取得 scoped input。
  ctx.slots.inject('conversation.chat.turnTail', () => ctx.slots.register({
    name: 'conversation.chat.turnTail',
    select: selectWuxiaResults,
    inject: (sessionId: any) => {
      let command: ((line: string) => void) | undefined
      let setDraft: ((text: string) => void) | undefined
      try {
        const session = sessions?.binding?.(sessionId)?.session
        if (session?.command) {
          command = (line: string) => { void session.command(line) }
        }
        try {
          const scoped = sessions?.scope?.(sessionId)
          const conversation = scoped?.get?.('conversation')
          const available = typeof conversation?.input?.for?.(scoped)?.setDraft === 'function'
          if (available) {
            setDraft = (text: string) => {
              const currentScope = sessions?.scope?.(sessionId)
              const input = currentScope?.get?.('conversation')?.input?.for?.(currentScope)
              input?.setDraft?.(text)
            }
          }
        } catch { /* conversation 不可用 */ }
      } catch { /* session 不可用 */ }
      let turnActivity
      try {
        turnActivity = turnActivityOf(ctx.uiConversation?.binding?.(sessionId))
      } catch { /* uiConversation 不可用 */ }
      return {
        command,
        setDraft,
        turnActivity,
        panelRequest: (slot: number, actions: Record<string, unknown>[]) =>
          requestPanel(ctx.remote, sessionId, slot, actions),
        battleRequest: (request: any) => requestBattle(ctx.remote, sessionId, request),
        deleteRequest: (slot: number) => requestDelete(ctx.remote, sessionId, slot),
      }
    },
  }, WuxiaTurnTail))

  ctx.slots.inject('conversation.composer.dock', () => ctx.slots.register({
    name: 'conversation.composer.dock',
    id: 'wuxia-party',
    order: 100,
    label: () => '武侠队伍',
    inject: (sessionId: string) => {
      let command: ((line: string) => void) | undefined
      try {
        const session = sessions?.binding?.(sessionId)?.session
        if (session?.command) command = (line: string) => { void session.command(line) }
      } catch { /* session 不可用 */ }
      return {
        sessionId,
        command,
        panelRequest: (slot: number, actions: Record<string, unknown>[]) =>
          requestPanel(ctx.remote, sessionId, slot, actions),
      }
    },
  }, PartyFloat))

  // 面板命令只作为 Client → Host 数据通道，不在对话流显示命令卡。
  ctx.slots.inject('conversation.chat.commandview', () => ctx.slots.register({
    name: 'conversation.chat.commandview',
    key: 'wuxia-panel',
  }, HiddenPanelCommand))
  ctx.slots.inject('conversation.chat.commandview', () => ctx.slots.register({
    name: 'conversation.chat.commandview',
    key: 'wuxia-battle',
  }, HiddenPanelCommand))

  // dsh 渲染模式下界面由 Card 托管：强制 shadow 内置 assistant-step 渲染器
  // （priority 更低者渲染），把 assistant 文本气泡改成「Think」折叠样式，
  // 默认收起、灰色，不喧宾夺主。
  ctx.slots.inject('conversation.chat.node', () => ctx.slots.register(
    { name: 'conversation.chat.node', key: 'assistant-step', priority: -1 },
    AssistantThinkNode,
  ))
}
