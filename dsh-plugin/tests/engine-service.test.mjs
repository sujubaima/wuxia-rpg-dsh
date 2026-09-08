import assert from 'node:assert/strict'
import { spawn } from 'node:child_process'
import { randomUUID } from 'node:crypto'
import { dirname, resolve } from 'node:path'
import { fileURLToPath } from 'node:url'
import test from 'node:test'

import { resolveEnginePaths, startEngineService } from '../lib/host/engine-service.js'

const HERE = dirname(fileURLToPath(import.meta.url))
const PLUGIN_DIR = resolve(HERE, '..')
const SKILL_DIR = resolve(PLUGIN_DIR, '..', 'wuxia-rpg')
const READY_PREFIX = '[engine-service-ready] '

function startPythonEngine() {
  const instanceId = randomUUID()
  const child = spawn(process.env.WUXIA_RPG_PYTHON || 'python3', [resolve(SKILL_DIR, 'scripts', 'engine_service.py')], {
    env: {
      ...process.env,
      HOST: '127.0.0.1',
      PORT: '0',
      WUXIA_RPG_ENGINE_INSTANCE_ID: instanceId,
      WUXIA_RPG_RENDER_MODULE: 'dsh',
      WUXIA_RPG_SKILL_DIR: SKILL_DIR,
    },
    stdio: ['ignore', 'pipe', 'pipe'],
  })

  const ready = new Promise((resolveReady, rejectReady) => {
    let buffer = ''
    let stderr = ''
    const timer = setTimeout(() => rejectReady(new Error(`engine ready 超时：${stderr}`)), 10000)
    child.stderr.on('data', data => { stderr += data.toString() })
    child.on('error', rejectReady)
    child.on('exit', code => rejectReady(new Error(`engine 提前退出 code=${String(code)}：${stderr}`)))
    child.stdout.on('data', data => {
      buffer += data.toString()
      let newline = buffer.indexOf('\n')
      while (newline !== -1) {
        const line = buffer.slice(0, newline).trim()
        buffer = buffer.slice(newline + 1)
        if (line.startsWith(READY_PREFIX)) {
          clearTimeout(timer)
          resolveReady(JSON.parse(line.slice(READY_PREFIX.length)))
          return
        }
        newline = buffer.indexOf('\n')
      }
    })
  })

  return { child, instanceId, ready }
}

async function stop(child) {
  if (child.exitCode !== null) return
  child.kill()
  await new Promise(resolveExit => child.once('exit', resolveExit))
}

test('resolveEnginePaths follows the plugin module location', () => {
  const moduleUrl = new URL('../lib/host/engine-service.js', import.meta.url).href
  const paths = resolveEnginePaths({}, moduleUrl)
  assert.equal(paths.pluginDir, PLUGIN_DIR)
  assert.equal(paths.scriptPath, resolve(SKILL_DIR, 'scripts', 'engine_service.py'))
  assert.equal(paths.skillDir, SKILL_DIR)
})

test('explicit paths override automatic discovery', () => {
  const paths = resolveEnginePaths({ engineServicePath: '/tmp/engine.py', skillDir: '/tmp/skill' })
  assert.equal(paths.scriptPath, '/tmp/engine.py')
  assert.equal(paths.skillDir, '/tmp/skill')
})

test('external serviceUrl is normalized without spawning', async () => {
  const url = await startEngineService({}, { serviceUrl: 'http://127.0.0.1:9000/' })
  assert.equal(url, 'http://127.0.0.1:9000')
})

test('autoStart=false requires an external serviceUrl', async () => {
  await assert.rejects(
    startEngineService({}, { autoStart: false }),
    /必须配置 serviceUrl/,
  )
})

test('Host startup waits for a verified dynamic-port service', async () => {
  let dispose
  const ctx = {
    logger: { info() {}, warn() {} },
    effect(register) { dispose = register() },
  }
  const serviceUrl = await startEngineService(ctx, {})
  try {
    assert.match(serviceUrl, /^http:\/\/127\.0\.0\.1:\d+$/)
    const health = await (await fetch(`${serviceUrl}/api/health`)).json()
    assert.equal(health.ok, true)
    assert.equal(health.service, 'wuxia-rpg-engine')
    assert.equal(health.engine, true)
    assert.equal(health.protocol_version, '1.0')
    assert.ok(health.instance_id)
    const manifest = await (await fetch(`${serviceUrl}/api/tools`)).json()
    assert.equal(manifest.tools.length, 8)
    const query = await fetch(`${serviceUrl}/api/v1/operations/query`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ 槽位: 0, 类型: '状态', 名称: ['不存在'] }),
    })
    assert.equal(query.status, 200)
  } finally {
    dispose?.()
  }
})

test('two default Python services receive distinct ports and identities', async () => {
  const first = startPythonEngine()
  const second = startPythonEngine()
  try {
    const [a, b] = await Promise.all([first.ready, second.ready])
    assert.equal(a.engine, true)
    assert.equal(b.engine, true)
    assert.equal(a.instance_id, first.instanceId)
    assert.equal(b.instance_id, second.instanceId)
    assert.notEqual(a.port, b.port)

    for (const [ready, expectedId] of [[a, first.instanceId], [b, second.instanceId]]) {
      const response = await fetch(`http://127.0.0.1:${ready.port}/api/health`)
      const health = await response.json()
      assert.deepEqual(health, {
        ok: true,
        service: 'wuxia-rpg-engine',
        instance_id: expectedId,
        engine: true,
        protocol_version: '1.0',
      })
    }
  } finally {
    await Promise.all([stop(first.child), stop(second.child)])
  }
})
