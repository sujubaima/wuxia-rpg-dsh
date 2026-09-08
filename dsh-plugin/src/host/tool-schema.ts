import type { ParameterSchemaSpec, ValueSchemaSpec } from '@deepseek-ai/dsh-tools'

export interface JsonSchemaNode {
  type: 'object' | 'array' | 'string' | 'number' | 'integer' | 'boolean' | 'null'
  description?: string
  title?: string
  properties?: Record<string, JsonSchemaNode>
  required?: string[]
  additionalProperties?: boolean
  items?: JsonSchemaNode
}

export interface WuxiaToolSpec {
  name: string
  operation: string
  title: string
  description: string
  input_schema: JsonSchemaNode
  output_schema: JsonSchemaNode
}

export interface WuxiaToolsManifest {
  protocol_version: string
  tools: WuxiaToolSpec[]
}

const TYPES = new Set(['object', 'array', 'string', 'number', 'integer', 'boolean', 'null'])

function assertSchema(value: unknown, path: string): asserts value is JsonSchemaNode {
  if (!value || typeof value !== 'object') throw new Error(`${path} 必须是对象`)
  const schema = value as Record<string, unknown>
  if (typeof schema.type !== 'string' || !TYPES.has(schema.type)) {
    throw new Error(`${path}.type 不受支持`)
  }
  if (schema.type === 'object') {
    if (schema.properties !== undefined && (!schema.properties || typeof schema.properties !== 'object')) {
      throw new Error(`${path}.properties 必须是对象`)
    }
    for (const [name, child] of Object.entries((schema.properties ?? {}) as Record<string, unknown>)) {
      assertSchema(child, `${path}.properties.${name}`)
    }
    if (schema.required !== undefined && (!Array.isArray(schema.required)
      || schema.required.some(item => typeof item !== 'string'))) {
      throw new Error(`${path}.required 必须是字符串数组`)
    }
  } else if (schema.type === 'array' && schema.items !== undefined) {
    assertSchema(schema.items, `${path}.items`)
  }
}

export function parseToolsManifest(value: unknown): WuxiaToolsManifest {
  if (!value || typeof value !== 'object') throw new Error('Tools Schema 必须是对象')
  const manifest = value as Record<string, unknown>
  if (typeof manifest.protocol_version !== 'string' || !manifest.protocol_version) {
    throw new Error('Tools Schema 缺少 protocol_version')
  }
  if (!Array.isArray(manifest.tools) || manifest.tools.length === 0) {
    throw new Error('Tools Schema 缺少 tools')
  }
  const names = new Set<string>()
  const operations = new Set<string>()
  const tools = manifest.tools.map((value, index) => {
    if (!value || typeof value !== 'object') throw new Error(`tools[${index}] 必须是对象`)
    const tool = value as Record<string, unknown>
    for (const key of ['name', 'operation', 'title', 'description'] as const) {
      if (typeof tool[key] !== 'string' || !tool[key]) throw new Error(`tools[${index}].${key} 缺失`)
    }
    const name = tool.name as string
    const operation = tool.operation as string
    if (names.has(name)) throw new Error(`工具名重复: ${name}`)
    if (operations.has(operation)) throw new Error(`operation 重复: ${operation}`)
    names.add(name)
    operations.add(operation)
    assertSchema(tool.input_schema, `tools[${index}].input_schema`)
    assertSchema(tool.output_schema, `tools[${index}].output_schema`)
    if (tool.input_schema.type !== 'object') throw new Error(`${name} input_schema 必须是 object`)
    return tool as unknown as WuxiaToolSpec
  })
  return { protocol_version: manifest.protocol_version, tools }
}

function annotations(schema: JsonSchemaNode): Record<string, string> {
  return {
    ...(schema.description ? { description: schema.description } : {}),
    ...(schema.title ? { title: schema.title } : {}),
  }
}

export function toValueSchema(schema: JsonSchemaNode): ValueSchemaSpec {
  const note = annotations(schema)
  switch (schema.type) {
    case 'object':
      return {
        type: 'object',
        ...note,
        properties: toParameterSchema(schema),
        additionalProperties: schema.additionalProperties !== false,
      }
    case 'array':
      return {
        type: 'array',
        ...note,
        ...(schema.items ? { items: toValueSchema(schema.items) } : {}),
      }
    case 'string':
    case 'number':
    case 'integer':
    case 'boolean':
    case 'null':
      return { type: schema.type, ...note } as ValueSchemaSpec
  }
}

export function toParameterSchema(schema: JsonSchemaNode): ParameterSchemaSpec {
  if (schema.type !== 'object') throw new Error('参数根 schema 必须是 object')
  const required = new Set(schema.required ?? [])
  const result: ParameterSchemaSpec = {}
  for (const [name, child] of Object.entries(schema.properties ?? {})) {
    result[name] = {
      ...toValueSchema(child),
      ...(required.has(name) ? { required: true as const } : {}),
    }
  }
  return result
}
