/** 武侠RPG dsh 插件 Host 入口：装配 engine service、工具与隐藏界面命令。 */

import type { Context } from '@deepseek-ai/cordis'
import {
  Config as ConfigSchema,
  DEFAULT_TIMEOUT,
  type Config as PluginConfig,
} from './config.js'
import { registerWuxiaBattleCommand } from './host/battle-command.js'
import { registerWuxiaCommands } from './host/commands.js'
import { startEngineService } from './host/engine-service.js'
import { registerWuxiaPanelCommand } from './host/panel-command.js'
import { registerWuxiaTools } from './host/tools.js'

export const name = 'wuxia-rpg'
export const inject = ['tools', 'commands']

export type Config = PluginConfig
export const Config = ConfigSchema

export async function apply(ctx: Context, config: Config = {}): Promise<void> {
  const serviceUrl = await startEngineService(ctx, config)
  const timeoutMs = config.timeoutMs ?? DEFAULT_TIMEOUT
  await registerWuxiaTools(ctx, serviceUrl, timeoutMs)
  registerWuxiaCommands(ctx, serviceUrl, timeoutMs)
  registerWuxiaPanelCommand(ctx, serviceUrl, timeoutMs)
  registerWuxiaBattleCommand(ctx, serviceUrl, timeoutMs)
}
