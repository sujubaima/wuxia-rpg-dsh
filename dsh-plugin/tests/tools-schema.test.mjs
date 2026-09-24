import assert from 'node:assert/strict'
import { readFile } from 'node:fs/promises'
import { dirname, resolve } from 'node:path'
import { fileURLToPath } from 'node:url'
import test from 'node:test'

import {
  parseToolsManifest,
  toParameterSchema,
  toValueSchema,
} from '../lib/host/tool-schema.js'

const HERE = dirname(fileURLToPath(import.meta.url))
const MANIFEST_PATH = resolve(HERE, '..', '..', 'wuxia-rpg', 'tools.json')

async function loadManifest() {
  return parseToolsManifest(JSON.parse(await readFile(MANIFEST_PATH, 'utf8')))
}

test('shared Tools Schema declares eleven unique operations', async () => {
  const manifest = await loadManifest()
  assert.equal(manifest.protocol_version, '1.9')
  assert.equal(manifest.tools.length, 11)
  assert.equal(new Set(manifest.tools.map(tool => tool.name)).size, 11)
  assert.equal(new Set(manifest.tools.map(tool => tool.operation)).size, 11)
  assert.equal(manifest.tools.find(tool => tool.name === 'wuxia_plot_writing')?.operation, 'plot-writing')
  assert.equal(manifest.tools.some(tool => tool.operation === 'turn-reset'), false)
})

test('standard JSON Schema converts to DSH parameter specs', async () => {
  const manifest = await loadManifest()
  const go = manifest.tools.find(tool => tool.name === 'wuxia_go')
  assert.ok(go)
  assert.match(go.input_schema.properties.槽位.description, /next_slot/)
  const goOutput = toValueSchema(go.output_schema)
  assert.equal(goOutput.properties.next_slot.type, 'integer')
  assert.equal(goOutput.properties.错误码.type, 'string')

  const scenePrepare = manifest.tools.find(tool => tool.name === 'wuxia_scene_prepare')
  assert.equal(scenePrepare.input_schema.properties.场景.minItems, 1)
  assert.match(scenePrepare.description, /不得修改/)
  const questPrepare = manifest.tools.find(tool => tool.name === 'wuxia_quest_prepare')
  assert.match(questPrepare.description, /judge 自动采用/)

  const recommend = manifest.tools.find(tool => tool.name === 'wuxia_recommend')
  assert.ok(recommend)
  const parameters = toParameterSchema(recommend.input_schema)
  assert.equal(parameters.槽位.type, 'integer')
  assert.equal(parameters.槽位.required, true)
  assert.equal(parameters.姓名.required, undefined)
  assert.equal(parameters.一级属性.type, 'object')
  assert.equal(parameters.一级属性.properties.内功.required, true)
  const output = toValueSchema(recommend.output_schema)
  assert.equal(output.type, 'object')
  assert.equal(output.additionalProperties, true)
})

test('manifest parser rejects duplicate operation ids', async () => {
  const manifest = await loadManifest()
  const broken = structuredClone(manifest)
  broken.tools[1].operation = broken.tools[0].operation
  assert.throws(() => parseToolsManifest(broken), /operation 重复/)
})
