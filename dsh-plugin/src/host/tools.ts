/** 从共享 Tools Schema 动态注册武侠引擎工具。 */

import type { Context } from '@deepseek-ai/cordis'
import { defineTool, type JsonValue } from '@deepseek-ai/dsh-tools'
import { callOperation, fetchToolsManifest } from './engine-client.js'
import { toParameterSchema, toValueSchema } from './tool-schema.js'

function renderEngineResult(value: JsonValue): { type: 'text'; text: string }[] {
  return [{ type: 'text', text: JSON.stringify(value, null, 2) }]
}

export async function registerWuxiaTools(
  ctx: Context,
  serviceUrl: string,
  timeoutMs: number,
): Promise<void> {
  const manifest = await fetchToolsManifest(serviceUrl, timeoutMs)
  for (const spec of manifest.tools) {
    const parameters = toParameterSchema(spec.input_schema)
    const outputSchema = toValueSchema(spec.output_schema)
    const options: any = {
      name: spec.name,
      description: spec.description,
      parameters,
      output: {
        schema: outputSchema,
        render: (_args: unknown, value: JsonValue) => renderEngineResult(value),
      },
      execute: (args: Record<string, JsonValue>) => (
        callOperation(serviceUrl, timeoutMs, spec.operation, args)
      ),
      presentCall: (args: Record<string, JsonValue>) => {
        const slot = typeof args.槽位 === 'number' ? args.槽位 : '?'
        return { card: 'generic', title: `${spec.title} (slot ${slot})`, kind: 'execute' }
      },
    }
    ctx.tools.register(defineTool(options))
  }
}
